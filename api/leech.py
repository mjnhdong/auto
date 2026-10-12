import os
import re
import json
import random
import xmlrpc.client
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import feedparser
import trafilatura

# ================= CẤU HÌNH HỆ THỐNG =================
TYPECHO_XMLRPC_URL = os.environ.get("TYPECHO_XMLRPC_URL", "https://your-domain.com/action/xmlrpc")
TYPECHO_USERNAME = os.environ.get("TYPECHO_USERNAME", "admin")
TYPECHO_PASSWORD = os.environ.get("TYPECHO_PASSWORD", "your_password")
DEFAULT_CATEGORY = os.environ.get("DEFAULT_CATEGORY", "Khác")
CRON_SECRET = os.environ.get("CRON_SECRET", "mat_khau_bao_ve_link")

# Danh sách RSS các trang công nghệ hàng đầu Việt Nam
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

# Từ khóa chặn: Nếu tiêu đề chứa các từ này thì bỏ qua (tránh bài PR/khuyến mãi rác)
BLACKLIST_WORDS = [
    "mã giảm giá", "voucher", "săn sale", "shopee", "lazada", "tiki",
    "khuyến mãi", "giảm sốc", "xả kho", "tuyển dụng", "quảng cáo"
]

# Bộ từ điển tự động nhận diện Tag (Từ khóa xuất hiện trong bài -> Tên Tag trên Typecho)
KEYWORD_DICTIONARY = {
    # Trí tuệ nhân tạo
    "ai": "AI",
    "trí tuệ nhân tạo": "AI",
    "chatgpt": "ChatGPT",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "claude": "Claude AI",
    "deepseek": "DeepSeek",
    "copilot": "Copilot",
    "llm": "Mô hình ngôn ngữ lớn",

    # Hãng công nghệ & Thiết bị
    "apple": "Apple",
    "iphone": "iPhone",
    "ipad": "iPad",
    "macbook": "MacBook",
    "ios": "iOS",
    "samsung": "Samsung",
    "galaxy": "Samsung Galaxy",
    "xiaomi": "Xiaomi",
    "redmi": "Xiaomi",
    "oppo": "OPPO",
    "vivo": "Vivo",
    "huawei": "Huawei",
    "realme": "Realme",
    "sony": "Sony",
    "pixel": "Google Pixel",
    "android": "Android",

    # Máy tính, Phần cứng & Chip
    "nvidia": "NVIDIA",
    "intel": "Intel",
    "amd": "AMD",
    "qualcomm": "Qualcomm",
    "snapdragon": "Snapdragon",
    "bán dẫn": "Chip bán dẫn",
    "vi xử lý": "Vi xử lý",
    "windows": "Windows",
    "microsoft": "Microsoft",
    "linux": "Linux",
    "laptop": "Laptop",
    "card đồ họa": "GPU",
    "rtx": "GPU",

    # Bảo mật, Lập trình & Mạng
    "hacker": "An ninh mạng",
    "mã độc": "An ninh mạng",
    "bảo mật": "Bảo mật",
    "lừa đảo": "Cảnh báo lừa đảo",
    "5g": "Mạng 5G",
    "6g": "Mạng 6G",
    "starlink": "Starlink",
    "elon musk": "Elon Musk",
    "google": "Google",
    "facebook": "Facebook",
    "meta": "Meta",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "zalo": "Zalo",
    "telegram": "Telegram",

    # Xe điện & Gaming
    "vinfast": "VinFast",
    "tesla": "Tesla",
    "xe điện": "Xe điện",
    "byd": "Xe điện",
    "playstation": "PlayStation",
    "ps5": "PS5",
    "nintendo": "Nintendo",
    "steam": "Gaming",
    "game": "Gaming",
    "esports": "eSports",
    "bitcoin": "Crypto",
    "blockchain": "Blockchain",
}

MAX_POSTS_PER_RUN = 2
# =====================================================


def get_existing_posts(server):
    """Lấy 40 bài gần nhất trên Typecho để kiểm tra trùng lặp."""
    try:
        recent_posts = server.metaWeblog.getRecentPosts(
            "1", TYPECHO_USERNAME, TYPECHO_PASSWORD, 40
        )
        existing_titles = {post.get("title", "").strip() for post in recent_posts}
        existing_bodies = " ".join(post.get("description", "") for post in recent_posts)
        return existing_titles, existing_bodies
    except Exception as e:
        print(f"Lỗi khi lấy danh sách bài cũ: {e}")
        return set(), ""


def is_blacklisted(title):
    """Kiểm tra xem tiêu đề có chứa từ khóa quảng cáo/săn sale không."""
    title_lower = title.lower()
    return any(bad_word in title_lower for bad_word in BLACKLIST_WORDS)


def extract_smart_tags(title, content, rss_entry):
    """Tự động quét tiêu đề, nội dung và RSS tags để tạo bộ từ khóa chuẩn SEO."""
    found_tags = []
    # Quét trên tiêu đề (ưu tiên cao) và 1500 ký tự đầu của bài viết
    search_text = f"{title} {content[:1500]}".lower()

    for keyword, tag_label in KEYWORD_DICTIONARY.items():
        # Dùng regex \b để bắt chính xác từ (tránh bắt nhầm chữ 'ai' trong 'tương lai')
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, search_text):
            if tag_label not in found_tags:
                found_tags.append(tag_label)

    # Lấy thêm tag gốc từ RSS Feed (nếu trang báo có cung cấp)
    if "tags" in rss_entry:
        for t in rss_entry.tags:
            term = t.get("term", "").strip()
            if 2 <= len(term) <= 25 and term not in found_tags:
                found_tags.append(term)

    # Luôn đảm bảo có ít nhất 2 tag mặc định nếu không bắt được từ khóa riêng
    if not found_tags:
        found_tags = ["Công nghệ", "Tin công nghệ"]
    else:
        found_tags.append("Công nghệ")

    # Giới hạn tối đa 6 tag mỗi bài để giao diện Typecho gọn đẹp
    return ", ".join(found_tags[:6])


def get_first_image(markdown_text, downloaded_html, rss_entry):
    """Tìm ảnh đầu tiên hợp lệ từ bài viết, og:image hoặc RSS summary."""
    md_images = re.findall(r"!\[.*?\]\((https?://[^\s\)]+)\)", markdown_text or "")
    for img in md_images:
        if not img.startswith("data:image") and not any(x in img.lower() for x in ["icon", "logo", "avatar", "pixel"]):
            return img

    if downloaded_html:
        meta = trafilatura.extract_metadata(downloaded_html)
        if meta and meta.image and meta.image.startswith("http"):
            return meta.image

    summary = rss_entry.get("summary", "") or rss_entry.get("description", "")
    rss_img = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', summary)
    if rss_img:
        return rss_img.group(1)

    return ""


def extract_article_and_thumb(url, rss_entry):
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, ""

    content = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_tables=True,
    )
    if not content:
        return None, ""

    thumb_url = get_first_image(content, downloaded, rss_entry)

    if thumb_url and thumb_url not in content:
        content = f"![]({thumb_url})\n\n{content}"

    return content, thumb_url


def run_leech():
    server = xmlrpc.client.ServerProxy(TYPECHO_XMLRPC_URL)
    existing_titles, existing_bodies = get_existing_posts(server)
    posted_list = []

    # Xáo trộn thứ tự các trang RSS để lấy bài đa dạng từ nhiều báo khác nhau
    feeds_to_scan = RSS_FEEDS.copy()
    random.shuffle(feeds_to_scan)

    for feed_url in feeds_to_scan:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue

        for entry in feed.entries[:6]:  # Chỉ xét 6 bài mới nhất của mỗi nguồn để tăng tốc
            if len(posted_list) >= MAX_POSTS_PER_RUN:
                return posted_list

            url = entry.get("link", "").strip()
            title = entry.get("title", "").strip()

            if not url or not title:
                continue

            # 1. Bỏ qua nếu bài chứa từ khóa quảng cáo/săn sale
            if is_blacklisted(title):
                continue

            # 2. Bỏ qua nếu bài đã từng được đăng
            if title in existing_titles or url in existing_bodies:
                continue

            content, thumb_url = extract_article_and_thumb(url, entry)
            if not content or len(content.strip()) < 250:
                continue

            # 3. Tự động tạo danh sách từ khóa (Tags) theo nội dung bài
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
