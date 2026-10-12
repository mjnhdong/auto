import os
import json
import xmlrpc.client
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import feedparser
import trafilatura

# Lấy cấu hình từ Environment Variables trên Vercel
TYPECHO_XMLRPC_URL = os.environ.get("TYPECHO_XMLRPC_URL", "[https://your-domain.com/action/xmlrpc](https://your-domain.com/action/xmlrpc)")
TYPECHO_USERNAME = os.environ.get("TYPECHO_USERNAME", "admin")
TYPECHO_PASSWORD = os.environ.get("TYPECHO_PASSWORD", "your_password")
DEFAULT_CATEGORY = os.environ.get("DEFAULT_CATEGORY", "Khác")
CRON_SECRET = os.environ.get("CRON_SECRET", "mat_khau_bao_ve_link")

RSS_FEEDS = [
    "https://vnexpress.net/rss/so-hoa.rss",
    "https://genk.vn/trang-chu.rss",
]

# Mỗi lần gọi chỉ lấy tối đa 2 bài để chạy cực nhanh, tránh timeout trên Vercel
MAX_POSTS_PER_RUN = 2


def get_existing_posts(server):
    """Lấy 30 bài viết gần nhất trên Typecho để kiểm tra trùng lặp (thay cho SQLite)."""
    try:
        recent_posts = server.metaWeblog.getRecentPosts(
            "1", TYPECHO_USERNAME, TYPECHO_PASSWORD, 30
        )
        existing_titles = {post.get("title", "").strip() for post in recent_posts}
        existing_bodies = " ".join(post.get("description", "") for post in recent_posts)
        return existing_titles, existing_bodies
    except Exception as e:
        print(f"Lỗi khi lấy danh sách bài cũ: {e}")
        return set(), ""


def extract_article(url):
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    return trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_tables=True,
    )


def run_leech():
    server = xmlrpc.client.ServerProxy(TYPECHO_XMLRPC_URL)
    existing_titles, existing_bodies = get_existing_posts(server)
    posted_list = []

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            if len(posted_list) >= MAX_POSTS_PER_RUN:
                return posted_list

            url = entry.link
            title = entry.title.strip()

            # Kiểm tra trùng tiêu đề hoặc trùng link nguồn trong nội dung bài cũ
            if title in existing_titles or url in existing_bodies:
                continue

            content = extract_article(url)
            if not content or len(content.strip()) < 200:
                continue

            full_body = (
                f"<!--markdown-->{content}\n\n"
                f"---\n*Nguồn: [Xem bài viết gốc]({url})*"
            )

            post_struct = {
                "title": title,
                "description": full_body,
                "categories": [DEFAULT_CATEGORY],
                "mt_keywords": "Công nghệ, Tin tức",
            }

            post_id = server.metaWeblog.newPost(
                "1", TYPECHO_USERNAME, TYPECHO_PASSWORD, post_struct, True
            )
            posted_list.append({"id": post_id, "title": title, "url": url})
            existing_titles.add(title)

    return posted_list


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Kiểm tra mã bí mật (?key=...) để người lạ không tự ý kích hoạt link
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
