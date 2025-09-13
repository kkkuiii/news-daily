#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日新闻导览 – 自动抓取 + DeepSeek 翻译 + 全新美观 HTML
"""
import os, sys, re, datetime, logging, smtplib, feedparser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from urllib.parse import urlparse
from openai import OpenAI

# ---------- 日志 ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- 邮件配置 ----------
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.qq.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SENDER_EMAIL', ''),
    'sender_password': os.getenv('SENDER_PASSWORD', ''),
    'receiver_email': os.getenv('RECEIVER_EMAIL', ''),
}

# ---------- 抓取器 ----------
class EnhancedNewsScraper:
    def __init__(self, deepseek_api_key: str = None):
        # 完整的新闻源配置 - 国内外结合
        self.rss_sources = [
            # 国内科技新闻源
            'https://36kr.com/feed ',
            'https://www.pingwest.com/feed ',
            'https://www.jiqizhixin.com/rss ',
            'https://www.leiphone.com/rss ',
            'https://tech.sina.com.cn/rss/index.shtml ',
            'https://tech.qq.com/web/rss_xml.htm ',
            'https://www.geekpark.net/rss ',
            
            # 国外科技新闻源
            'https://www.wired.com/feed/rss ',
            'https://techcrunch.com/feed/ ',
            'https://www.theverge.com/rss/index.xml ',
            'https://arstechnica.com/feed/ ',
            'https://www.engadget.com/rss.xml ',
        ]
        self.categories = {
            '科技': ['technology', 'tech', '科技', '数码', '互联网', '软件', '硬件', '创新', 'startup', 'digital', 'internet'],
            '金融': ['finance', 'financial', '金融', '股市', '银行', '投资', '经济', 'market', 'economy', 'stock', 'banking'],
            'AI': ['ai', 'artificial intelligence', '人工智能', '机器学习', '深度学习', '算法', 'ml', 'neural', 'chatgpt', '大模型'],
            '教育': ['education', 'educational', '教育', '学校', '大学', '学习', '培训', 'edu', 'university', 'school'],
            '医疗': ['health', 'medical', '医疗', '健康', '医院', '疾病', '药物', 'medicine', 'hospital', 'doctor'],
            '环保': ['environment', 'climate', '环保', '环境', '气候变化', '可持续', 'green', 'sustainability', 'carbon', 'eco'],
            '汽车': ['car', 'auto', '汽车', '电动车', '电动汽车', 'tesla', 'ev', 'vehicle'],
            '游戏': ['game', 'gaming', '游戏', '电竞', '电子竞技', 'playstation', 'xbox'],
            '区块链': ['blockchain', 'crypto', '区块链', '加密货币', '比特币', 'ethereum', 'nft'],
        }
        self.articles_by_category = {c: [] for c in self.categories}
        self.processed_urls = set()
        if not deepseek_api_key:
            raise ValueError("DeepSeek API Key is required")
        self.deepseek_client = OpenAI(api_key=deepseek_api_key, base_url="https://api.deepseek.com")
        logger.info("✅ DeepSeek 客户端初始化成功")

    # ------------ 翻译 ------------
    def _translate_titles(self, articles: list[dict]) -> list[dict]:
        if not articles:
            return articles
        en_titles = [a["title"] for a in articles]
        prompt = "请将下列英文新闻标题翻译成地道中文，每行格式：中文标题 (English Title)\n" + "\n".join(en_titles)
        try:
            rsp = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000
            )
            lines = [ln.strip() for ln in rsp.choices[0].message.content.strip().splitlines() if ln.strip()]
        except Exception as e:
            logger.warning(f"翻译失败: {e}")
            lines = en_titles
        for a, new_line in zip(articles, lines):
            a["title"] = new_line
        return articles

    # ------------ 抓取 ------------
    def fetch_news_from_rss(self):
        headers = {'User-Agent': 'Mozilla/5.0'}
        for rss_url in self.rss_sources:
            try:
                feed = feedparser.parse(rss_url, request_headers=headers)
                for entry in feed.entries[:6]:
                    title = getattr(entry, 'title', '无标题')
                    link = getattr(entry, 'link', '')
                    summary = getattr(entry, 'summary', '')[:400] + "..."
                    if link and link not in self.processed_urls:
                        self.processed_urls.add(link)
                        is_relevant, cats = self.categorize_article(title, summary)
                        if is_relevant:
                            art = {
                                'title': title.strip(),
                                'url': link.strip(),
                                'summary': summary.strip() or "暂无摘要",
                                'publish_date': getattr(entry, 'published', None),
                                'source': urlparse(rss_url).netloc
                            }
                            for c in cats:
                                if not any(a['url'] == link for a in self.articles_by_category[c]):
                                    self.articles_by_category[c].append(art)
            except Exception as e:
                logger.error(f"RSS失败 {rss_url}: {e}")

    def categorize_article(self, title: str, content: str):
        full = (title + " " + content).lower()
        match = []
        for c, kw in self.categories.items():
            score = sum(2 if k in title.lower() else 1 for k in kw if k in full)
            if score >= 1:
                match.append(c)
        return bool(match), match

    def remove_duplicates(self):
        for c in self.articles_by_category:
            seen = set()
            self.articles_by_category[c] = [a for a in self.articles_by_category[c] if not (a['url'] in seen or seen.add(a['url']))]

    def scrape_news(self):
        logger.info("🌐 开始抓取新闻...")
        self.fetch_news_from_rss()
        self.remove_duplicates()
        logger.info("📈 抓取完成")

    # ------------ 摘要 ------------
    def generate_daily_summary(self) -> str:
        titles = []
        stats = []
        for c, arts in self.articles_by_category.items():
            if arts:
                stats.append(f"{c}:{len(arts)}篇")
                titles += [f"[{c}] {a['title']}" for a in arts[:10]]
        if not titles:
            return "今日导览摘要：暂无新闻。"
        titles_text = "\n".join(titles[:60])
        stats_text = ", ".join(stats)
        prompt = f"""请基于以下新闻标题生成400-600字中文摘要，要求概括趋势、焦点，以“今日导览摘要：”开头。
统计：{stats_text}
标题：
{titles_text}"""
        try:
            rsp = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1000
            )
            s = rsp.choices[0].message.content.strip()
            return s if s.startswith("今日导览摘要：") else "今日导览摘要：" + s
        except Exception as e:
            return f"今日导览摘要：DeepSeek 调用失败 - {e}"

    # ------------ 全新 HTML ------------
    def generate_html_report(self) -> str:
        cur_date = datetime.datetime.now().strftime("%Y-%m-%d")
        cur_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        summary = self.generate_daily_summary()
        cat_counts = [(c, len(a)) for c, a in self.articles_by_category.items() if a]
        cat_counts.sort(key=lambda x: x[1], reverse=True)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>每日新闻导览 - {cur_date}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root{{--bg:#f4f7fa;--card:#ffffff;--primary:#0d6efd;--secondary:#6c757d;--accent:#ff7f50;--line:#e6e9ef;--text:#212529;--small:#6c757d}}
    body{{margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.6}}
    .container{{max-width:840px;margin:30px auto;padding:0 16px}}
    header{{text-align:center;margin-bottom:40px}}
    .date{{font-size:14px;color:var(--small);margin-bottom:8px}}
    h1{{font-size:32px;margin:0 0 8px}}
    .summary{{background:var(--card);border-left:4px solid var(--primary);padding:24px;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,.05);margin-bottom:40px}}
    .summary h2{{margin:0 0 12px;font-size:20px}}
    .category{{margin-bottom:32px}}
    .category h2{{font-size:22px;margin:0 0 16px;display:flex;align-items:center}}
    .category h2 .count{{font-size:14px;margin-left:10px;background:var(--primary);color:#fff;padding:4px 10px;border-radius:12px}}
    .article-list{{display:grid;gap:14px}}
    .article{{background:var(--card);padding:20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.06);transition:transform .2s,box-shadow .2s}}
    .article:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.08)}}
    .article a{{text-decoration:none;color:var(--text);font-weight:600;font-size:16px}}
    .article a:hover{{color:var(--primary)}}
    .meta{{font-size:13px;color:var(--small);margin-top:6px}}
    .summary-text{{font-size:14px;color:var(--small);margin-top:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
    .stats{{background:var(--card);padding:20px;border-radius:8px;text-align:center;font-size:14px;color:var(--small)}}
    footer{{text-align:center;font-size:13px;color:var(--small);margin:40px 0 20px}}
    @media(max-width:600px){{h1{{font-size:24px}}.article a{{font-size:15px}}}}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="date">{cur_date} · 每日新闻导览</div>
      <h1>📰 今日新闻速览</h1>
    </header>

    <div class="summary">
      <h2>🎯 今日导览摘要</h2>
      <p>{summary}</p>
    </div>"""

        for c, cnt in cat_counts:
            arts = self._translate_titles(self.articles_by_category[c])
            html += f'<div class="category"><h2>{c}<span class="count">{cnt}</span></h2><div class="article-list">'
            for a in arts:
                title = a['title'][:80] + "…" if len(a['title']) > 80 else a['title']
                pub = str(a.get('publish_date') or '')[:16]
                src = a['source']
                summ = re.sub('<[^<]+?>', '', a.get('summary', '') or "暂无摘要")[:120] + "…"
                html += f"""
<div class="article">
  <a href="{a['url']}" target="_blank">{title}</a>
  <div class="meta">🕐 {pub} · 📰 {src}</div>
  <div class="summary-text">📝 {summ}</div>
</div>"""
            html += '</div></div>'

        total = sum(len(a) for a in self.articles_by_category.values())
        html += f'<div class="stats">共收录 <strong>{total}</strong> 篇文章 · 涵盖 <strong>{len(cat_counts)}</strong> 个领域 · 自动生成于 {cur_time}</div>'
        html += f'<footer>Powered by DeepSeek AI · {cur_time}</footer></div></body></html>'
        return html

# ---------- 邮件 ----------
class EmailSender:
    @staticmethod
    def send_html_email(html: str, subject: str = None, config: dict = None) -> bool:
        cfg = config or EMAIL_CONFIG
        if not all(cfg.get(k) for k in ('sender_email', 'sender_password', 'receiver_email')):
            logger.error("❌ 邮件配置不完整")
            return False
        subject = subject or f"每日新闻导览-{datetime.datetime.now().strftime('%Y-%m-%d')}"
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = cfg['sender_email']
            msg['To'] = cfg['receiver_email']
            msg['Subject'] = Header(subject, 'utf-8')
            msg.attach(MIMEText(html, 'html', 'utf-8'))
            with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as srv:
                srv.starttls()
                srv.login(cfg['sender_email'], cfg['sender_password'])
                srv.send_message(msg)
            logger.info("✅ 邮件发送成功")
            return True
        except Exception as e:
            logger.error(f"❌ 邮件发送失败: {e}")
            return False

# ---------- main ----------
def main():
    logger.info("🚀 开始新闻日报任务...")
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    SENDER_EMAIL = os.getenv('SENDER_EMAIL')
    SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
    RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL')
    if not DEEPSEEK_API_KEY:
        logger.error("❌ 请设置 DEEPSEEK_API_KEY")
        sys.exit(1)
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL]):
        logger.error("❌ 请设置完整邮件环境变量")
        sys.exit(1)
    EMAIL_CONFIG.update({
        'sender_email': SENDER_EMAIL,
        'sender_password': SENDER_PASSWORD,
        'receiver_email': RECEIVER_EMAIL,
    })
    try:
        scraper = EnhancedNewsScraper(DEEPSEEK_API_KEY)
        scraper.scrape_news()
        html = scraper.generate_html_report()
        with open('/tmp/news_report.html', 'w', encoding='utf-8') as f:
            f.write(html)
        EmailSender.send_html_email(html)
    except Exception as e:
        logger.error(f"❌ 执行出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
