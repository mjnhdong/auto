import os
import re
import json
import html
import random
import xmlrpc.client
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urljoin, quote
import feedparser
import trafilatura
from lxml import html as lxml_html

# ================= CẤU HÌNH HỆ THỐNG =================
TYPECHO_XMLRPC_URL = os.environ.get("TYPECHO_XMLRPC_URL", "https://your-domain.com/action/xmlrpc")
TYPECHO_USERNAME = os.environ.get("TYPECHO_USERNAME", "admin")
TYPECHO_PASSWORD = os.environ.get("TYPECHO_PASSWORD", "your_password")
DEFAULT_CATEGORY = os.environ.get("DEFAULT_CATEGORY", "Khác")
CRON_SECRET = os.environ.get("CRON_SECRET", "mat_khau_bao_ve_link")

USE_IMAGE_PROXY = True

RSS_FEEDS = [
    "https://vnexpress.net/rss/so-hoa.rss",
    "https://genk.vn/trang-chu.rss",
    "https://genk.vn/mobile.rss",
    "https://genk.vn/tin-ict.rss",
    "https://dantri.com.vn/rss/cong-nghe.rss",
    "https://thanhnien.vn/rss/cong-nghe.rss",
    "https://tuoitre.vn/rss/nhip-song-so.rss",
    "https://vietnamnet.vn/rss/cong-nghe.rss",
    "https://vtv.vn/cong-nghe.rss",
    "https://tinhte.vn/rss",
]

BLACKLIST_WORDS = [
    "mã giảm giá", "voucher", "săn sale", "shopee", "lazada", "tiki",
    "khuyến mãi", "giảm sốc", "xả kho", "tuyển dụng", "quảng cáo"
]

KEYWORD_DICTIONARY = {
    "ai": "AI",
    "trí tuệ nhân tạo": "AI",
    "chatgpt": "ChatGPT",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "claude": "Claude AI",
    "deepseek": "DeepSeek",
    "copilot": "Copilot",
    "apple": "Apple",
    "iphone": "iPhone",
    "ipad": "iPad",
    "macbook": "MacBook",
    "ios": "iOS",
    "samsung": "Samsung",
    "galaxy": "Samsung Galaxy",
    "xiaomi": "Xiaomi",
    "oppo": "OPPO",
    "vivo": "Vivo",
    "huawei": "Huawei",
    "realme": "Realme",
    "sony": "Sony",
    "android": "Android",
    "nvidia": "NVIDIA",
    "intel": "Intel",
    "amd": "AMD",
    "qualcomm": "Qualcomm",
    "snapdragon": "Snapdragon",
    "bán dẫn": "Chip bán dẫn",
    "windows": "Windows",
    "microsoft": "Microsoft",
    "linux": "Linux",
    "laptop": "Laptop",
    "rtx": "GPU",
    "hacker": "An ninh mạng",
    "mã độc": "An ninh mạng",
    "bảo mật": "Bảo mật",
    "lừa đảo": "Cảnh báo lừa đảo",
    "5g": "Mạng 5G",
    "6g": "Mạng 6G",
    "starlink": "Starlink",
    "google": "Google",
    "facebook": "Facebook",
    "meta": "Meta",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "zalo": "Zalo",
    "telegram": "Telegram",
    "vinfast": "VinFast",
    "tesla": "Tesla",
    "xe điện": "Xe điện",
    "ps5": "PS5",
    "steam": "Gaming",
    "game": "Gaming",
    "bitcoin": "Crypto",
    "blockchain": "Blockchain",
}

MAX_POSTS_PER_RUN = 2
# =====================================================


def clean_html_entities(text):
    """Giải mã triệt để các ký tự HTML bị mã hóa kép như &amp;apos;, &apos;, &quot;, &#39;."""
    if not text:
        return ""
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text.replace("\xa0", " ").strip()


def clean_and_proxy_img_url(img_url, base_url):
    if not img_url:
        return ""
    img_url = html.unescape(img_url.strip())

    if img_url.startswith("data:") or any(
        bad in img_url.lower() for bad in ["blank.gif", "loading", "avatar", "icon", "logo", "1x1"]
    ):
        return ""

    if " " in img_url or "," in img_url:
        first_part = img_url.split(",")[0].strip().split(" ")[0].strip()
        if first_part.startswith("http") or first_part.startswith("/"):
            img_url = first_part

    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif not img_url.startswith("http"):
        img_url = urljoin(base_url, img_url)

    img_url = img_url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")

    if USE_IMAGE_PROXY and not img_url.startswith("https://wsrv.nl/"):
        return f"https://wsrv.nl/?url={quote(img_url, safe='')}"

    return img_url


def preprocess_html_images(raw_html, base_url):
    try:
        tree = lxml_html.fromstring(raw_html)

        for picture in tree.xpath("//picture"):
            real_url = ""
            for source in picture.xpath(".//source"):
                srcset = (
                    source.get("data-srcset")
                    or source.get("srcset")
                    or source.get("data-src")
                    or ""
                )
                cleaned = clean_and_proxy_img_url(srcset, base_url)
                if cleaned:
                    real_url = cleaned
                    break

            img_tag = picture.find(".//img")
            if img_tag is not None and real_url:
                img_tag.set("src", real_url)

        lazy_attrs = [
            "data-original",
            "data-src",
            "data-lazy-src",
            "data-hi-res-src",
            "data-url",
            "data-lazyload",
            "data-srcset",
            "srcset",
            "src",
        ]

        for img in tree.xpath("//img"):
            best_url = ""
            for attr in lazy_attrs:
                val = img.get(attr)
                if val:
                    cleaned = clean_and_proxy_img_url(val, base_url)
                    if cleaned:
                        best_url = cleaned
                        break

            if best_url:
                img.attrib.clear()
                img.set("src", best_url)
            else:
                img.getparent().remove(img)

        return lxml_html.tostring(tree, encoding="unicode")
    except Exception as e:
        print(f"Lỗi tiền xử lý ảnh HTML: {e}")
        return raw_html


def get_existing_posts(server):
    try:
        recent_posts = server.metaWeblog.getRecentPosts(
            "1", TYPECHO_USERNAME, TYPECHO_PASSWORD, 40
        )
        existing_titles = {
            clean_html_entities(post.get("title", "")) for post in recent_posts
        }
        existing_bodies = " ".join(post.get("description", "") for post in recent_posts)
        return existing_titles, existing_bodies
    except Exception as e:
        print(f"Lỗi khi lấy danh sách bài cũ: {e}")
        return set(), ""


def is_blacklisted(title):
    title_lower = title.lower()
    return any(bad_word in title_lower for bad_word in BLACKLIST_WORDS)


def extract_smart_tags(title, content, rss_entry):
    found_tags = []
    search_text = f"{title} {content[:1500]}".lower()

    for keyword, tag_label in KEYWORD_DICTIONARY.items():
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, search_text):
            if tag_label not in found_tags:
                found_tags.append(tag_label)

    if "tags" in rss_entry:
        for t in rss_entry.tags:
            term = clean_html_entities(t.get("term", ""))
            if 2 <= len(term) <= 25 and term not in found_tags:
                found_tags.append(term)

    if not found_tags:
        found_tags = ["Công nghệ", "Tin công nghệ"]
    else:
        found_tags.append("Công nghệ")

    return ", ".join(found_tags[:6])


def get_first_image(markdown_text, raw_html, rss_entry, base_url):
    md_images = re.findall(r"!\[.*?\]\((https?://[^\s\)]+)\)", markdown_text or "")
    for img in md_images:
        if img.startswith("http"):
            return img

    if raw_html:
        meta = trafilatura.extract_metadata(raw_html)
        if meta and meta.image:
            cleaned = clean_and_proxy_img_url(meta.image, base_url)
            if cleaned:
                return cleaned

    summary = rss_entry.get("summary", "") or rss_entry.get("description", "")
    rss_img = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', summary)
    if rss_img:
        cleaned = clean_and_proxy_img_url(rss_img.group(1), base_url)
        if cleaned:
            return cleaned

    return ""


def extract_article_and_thumb(url, rss_entry):
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, ""

    fixed_html = preprocess_html_images(downloaded, url)

    content = trafilatura.extract(
        fixed_html,
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_tables=True,
    )
    if not content:
        return None, ""

    content = re.sub(r"!\[.*?\]\(data:image[^\)]+\)", "", content)
    content = clean_html_entities(content)

    thumb_url = get_first_image(content, downloaded, rss_entry, url)

    if thumb_url and thumb_url not in content:
        content = f"![]({thumb_url})\n\n{content}"

    return content, thumb_url


def run_leech():
    server = xmlrpc.client.ServerProxy(TYPECHO_XMLRPC_URL)
    existing_titles, existing_bodies = get_existing_posts(server)
    posted_list = []

    feeds_to_scan = RSS_FEEDS.copy()
    random.shuffle(feeds_to_scan)

    for feed_url in feeds_to_scan:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue

        for entry in feed.entries[:6]:
            if len(posted_list) >= MAX_POSTS_PER_RUN:
                return posted_list

            url = entry.get("link", "").strip()
            # Giải mã các thực thể HTML bị lỗi ngay từ lúc đọc tiêu đề RSS
            title = clean_html_entities(entry.get("title", ""))

            if not url or not title:
                continue

            if is_blacklisted(title):
                continue

            if title in existing_titles or url in existing_bodies:
                continue

            content, thumb_url = extract_article_and_thumb(url, entry)
            if not content or len(content.strip()) < 250:
                continue

            smart_keywords = extract_smart_tags(title, content, entry)

            full_body = (
                f"<!--markdown-->{content}\n\n"
                f"---\n*Nguồn: [Xem bài viết gốc]({url})*"
            )

            post_struct = {
                "title": title,
                "description": full_body,
                "categories": [DEFAULT_CATEGORY],
                "mt_keywords": smart_keywords,
                "custom_fields": [
                    {"key": "thumb", "value": thumb_url}
                ] if thumb_url else [],
            }

            post_id = server.metaWeblog.newPost(
                "1", TYPECHO_USERNAME, TYPECHO_PASSWORD, post_struct, True
            )
            posted_list.append({
                "id": post_id,
                "title": title,
                "tags": smart_keywords,
                "thumb": thumb_url,
                "url": url,
            })
            existing_titles.add(title)

    return posted_list


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        key = query_components.get("key", [""])[0]

        if key != CRON_SECRET:
            self.send_response(401)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Sai mã CRON_SECRET"}).encode("utf-8"))
            return

        try:
            results = run_leech()
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            response_data = {
                "status": "success",
                "posted_count": len(results),
                "posts": results,
            }
            self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
