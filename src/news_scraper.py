import requests
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime
import time
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import sys
from urllib.parse import urljoin, urlparse
import re

# DeepSeek 集成
from openai import OpenAI

# 配置日志
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 邮件配置（从环境变量获取）
EMAIL_CONFIG = {
    'smtp_server': os.getenv('SMTP_SERVER', 'smtp.qq.com'),
    'smtp_port': int(os.getenv('SMTP_PORT', '587')),
    'sender_email': os.getenv('SENDER_EMAIL', ''),
    'sender_password': os.getenv('SENDER_PASSWORD', ''),
    'receiver_email': os.getenv('RECEIVER_EMAIL', ''),
}

class EnhancedNewsScraper:
    def __init__(self, deepseek_api_key: str = None):
        # 完整的新闻源配置 - 国内外结合
        self.rss_sources = [
            # 国内科技新闻源
            'https://36kr.com/feed',
            'https://www.pingwest.com/feed',
            'https://www.jiqizhixin.com/rss',
            'https://www.leiphone.com/rss',
            'https://tech.sina.com.cn/rss/index.shtml',
            'https://tech.qq.com/web/rss_xml.htm',
            'https://www.geekpark.net/rss',
            
            # 国外科技新闻源
            'https://www.wired.com/feed/rss',
            'https://techcrunch.com/feed/',
            'https://www.theverge.com/rss/index.xml',
            'https://arstechnica.com/feed/',
            'https://www.engadget.com/rss.xml',
        ]
        
        # 完整的分类配置（保持原样）
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
        
        # 存储结果
        self.articles_by_category = {category: [] for category in self.categories.keys()}
        self.processed_urls = set()
        
        # 初始化 DeepSeek 客户端（强制要求）
        if not deepseek_api_key:
            logger.error("❌ 错误：必须提供 DeepSeek API Key！")
            raise ValueError("DeepSeek API Key is required")
        
        try:
            self.deepseek_client = OpenAI(
                api_key=deepseek_api_key,
                base_url="https://api.deepseek.com"
            )
            logger.info("✅ DeepSeek API 客户端初始化成功")
        except Exception as e:
            logger.error(f"❌ DeepSeek API 客户端初始化失败: {e}")
            raise
    
    def fetch_news_from_rss(self):
        """从RSS源获取新闻"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        successful_sources = 0
        total_articles = 0
        
        for rss_url in self.rss_sources:
            try:
                logger.info(f"📡 正在处理RSS源: {rss_url}")
                
                # 使用 feedparser 解析 RSS
                feed = feedparser.parse(rss_url, request_headers=headers)
                
                if feed.bozo and feed.bozo_exception:
                    logger.warning(f"⚠️ RSS源可能有问题 {rss_url}: {feed.bozo_exception}")
                
                if not feed.entries:
                    logger.warning(f"⚠️ RSS源没有内容 {rss_url}")
                    continue
                
                # 处理文章条目
                entries_processed = 0
                for entry in feed.entries[:6]:  # 每个源最多处理6篇文章
                    try:
                        # 提取文章信息
                        title = getattr(entry, 'title', '无标题')
                        link = getattr(entry, 'link', '')
                        summary = getattr(entry, 'summary', '')
                        description = getattr(entry, 'description', '')
                        content = getattr(entry, 'content', [{}])
                        
                        # 合并多种内容源
                        content_text = ""
                        if summary:
                            content_text = summary
                        elif description:
                            content_text = description
                        elif content and isinstance(content, list) and len(content) > 0:
                            content_text = str(content[0].get('value', ''))
                        
                        # 限制内容长度
                        if len(content_text) > 400:
                            content_text = content_text[:400] + "..."
                        
                        # 发布时间
                        pub_date = None
                        if hasattr(entry, 'published'):
                            pub_date = entry.published
                        elif hasattr(entry, 'updated'):
                            pub_date = entry.updated
                        
                        # 去重检查
                        if link in self.processed_urls:
                            continue
                        self.processed_urls.add(link)
                        
                        if link and title:
                            # 分类文章
                            is_relevant, categories = self.categorize_article(title, content_text)
                            
                            if is_relevant and categories:
                                article_data = {
                                    'title': title.strip(),
                                    'url': link.strip(),
                                    'summary': content_text.strip() if content_text else "暂无摘要",
                                    'publish_date': pub_date,
                                    'source': urlparse(rss_url).netloc
                                }
                                
                                # 添加到对应分类
                                for category in categories:
                                    # 避免重复添加
                                    if not any(a['url'] == link for a in self.articles_by_category[category]):
                                        self.articles_by_category[category].append(article_data)
                                
                                logger.info(f"🎯 获取相关文章: [{','.join(categories)}] {title[:40]}...")
                                entries_processed += 1
                                total_articles += 1
                                
                    except Exception as e:
                        logger.debug(f"处理RSS条目时出错: {e}")
                        continue
                
                if entries_processed > 0:
                    successful_sources += 1
                    logger.info(f"📊 从 {rss_url} 处理了 {entries_processed} 篇相关文章")
                        
            except Exception as e:
                logger.error(f"❌ 处理RSS源失败 {rss_url}: {e}")
                continue
        
        logger.info(f"📈 总结: 处理了 {successful_sources} 个RSS源，共获取 {total_articles} 篇相关文章")
    
    def categorize_article(self, title: str, content: str = "") -> tuple:
        """对文章进行分类（保持原有逻辑）"""
        full_content = (title + " " + content).lower()
        
        relevant_categories = []
        match_scores = {}
        
        # 计算每个分类的匹配分数
        for category, keywords in self.categories.items():
            score = 0
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in full_content:
                    score += 1
                    # 标题中的关键词权重更高
                    if keyword_lower in title.lower():
                        score += 2
            
            match_scores[category] = score
        
        # 根据分数确定相关分类（降低阈值提高召回率）
        for category, score in match_scores.items():
            # 更宽松的阈值
            threshold = 1  # 降低阈值
            if score >= threshold:
                relevant_categories.append(category)
        
        return len(relevant_categories) > 0, relevant_categories
    
    def remove_duplicates(self):
        """去除重复文章"""
        total_before = sum(len(articles) for articles in self.articles_by_category.values())
        
        for category in self.articles_by_category:
            seen_urls = set()
            unique_articles = []
            
            for article in self.articles_by_category[category]:
                if article['url'] not in seen_urls:
                    seen_urls.add(article['url'])
                    unique_articles.append(article)
            
            self.articles_by_category[category] = unique_articles
        
        total_after = sum(len(articles) for articles in self.articles_by_category.values())
        logger.info(f"🗑️ 去重完成: {total_before} → {total_after} 篇文章")
    
    def scrape_news(self):
        """抓取新闻"""
        logger.info("🌐 开始从RSS源获取新闻...")
        self.fetch_news_from_rss()
        
        # 去重
        self.remove_duplicates()
        
        logger.info("📈 新闻获取完成")
    
    def generate_daily_summary(self) -> str:
        """生成今日新闻摘要（强制使用DeepSeek大模型）"""
        logger.info("🤖 强制使用 DeepSeek 大模型生成智能摘要...")
        
        # 收集所有文章标题
        all_titles = []
        category_stats = {}
        
        for category, articles in self.articles_by_category.items():
            if articles:
                category_stats[category] = len(articles)
                for article in articles[:10]:  # 每个分类最多取10篇文章
                    all_titles.append(f"[{category}] {article['title']}")
        
        if not all_titles:
            error_msg = "今日导览摘要：DeepSeek API 调用失败，暂无新闻内容可供分析。"
            logger.error("❌ 没有文章可供分析")
            return error_msg
        
        # 准备数据
        titles_text = "\n".join(all_titles[:60])  # 最多60篇文章
        stats_text = ", ".join([f"{cat}:{count}篇" for cat, count in category_stats.items()])
        
        prompt = f"""
        请基于以下今日新闻标题，生成一段400-600字的中文摘要。要求：
        1. 不要机械复述标题，要进行概括与串联
        2. 提炼出当日新闻的主要趋势、关注焦点或舆论动向
        3. 风格自然流畅，具有整体感
        4. 突出最重要的几个主题方向
        5. 可以适当分析各领域的发展态势
        6. 以专业但易懂的语言表达
        
        今日新闻统计：{stats_text}
        
        新闻标题列表：
        {titles_text}
        
        请以"今日导览摘要："开头，直接输出摘要内容，不要包含其他说明文字。
        """
        
        logger.info(f"📊 准备发送 {len(all_titles)} 篇文章标题给 DeepSeek AI")
        
        try:
            response = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位专业的新闻分析师和科技观察者，擅长总结和分析新闻趋势。请用中文回答。"},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=0.7,
                max_tokens=1000
            )
            
            summary = response.choices[0].message.content.strip()
            if not summary.startswith("今日导览摘要："):
                summary = "今日导览摘要：" + summary
            
            logger.info("✅ DeepSeek 大模型摘要生成成功！")
            return summary
            
        except Exception as e:
            error_msg = f"今日导览摘要：DeepSeek API 调用失败 - {str(e)}。请检查API密钥和网络连接。"
            logger.error(f"❌ DeepSeek 大模型调用失败: {e}")
            return error_msg
    
    def generate_html_report(self) -> str:
        """生成HTML格式的日报"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 生成摘要（强制使用DeepSeek）
        daily_summary = self.generate_daily_summary()
        
        # 按文章数量排序分类
        category_article_counts = [(cat, len(articles)) for cat, articles in self.articles_by_category.items() if articles]
        category_article_counts.sort(key=lambda x: x[1], reverse=True)
        
        # HTML 模板
        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日新闻导览 - {current_date}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        h1 {{
            color: #2c3e50;
            margin: 0 0 10px 0;
        }}
        .meta-info {{
            color: #7f8c8d;
            font-size: 14px;
        }}
        .summary {{
            background-color: #fff8e1;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid #ffc107;
        }}
        .summary h2 {{
            margin-top: 0;
            color: #2c3e50;
        }}
        .category {{
            background-color: #f8f9fa;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 25px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .category h2 {{
            margin-top: 0;
            color: #2c3e50;
            border-bottom: 2px solid #eee;
            padding-bottom: 15px;
        }}
        .article-item {{
            margin: 20px 0;
            padding: 20px;
            background: white;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            transition: transform 0.2s ease;
        }}
        .article-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        .article-title {{
            font-size: 17px;
            font-weight: 600;
            margin: 0 0 10px 0;
        }}
        .article-title a {{
            color: #3498db;
            text-decoration: none;
        }}
        .article-title a:hover {{
            text-decoration: underline;
        }}
        .article-meta {{
            font-size: 13px;
            color: #7f8c8d;
            margin: 8px 0;
        }}
        .article-summary {{
            font-size: 14px;
            color: #555;
            margin: 12px 0 0 0;
            line-height: 1.6;
            background-color: #fafafa;
            padding: 12px;
            border-radius: 4px;
            border-left: 3px solid #3498db;
        }}
        .stats {{
            background-color: #e8f4f8;
            padding: 20px;
            border-radius: 8px;
            margin-top: 40px;
        }}
        .stats h2 {{
            margin-top: 0;
            color: #2c3e50;
        }}
        footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 25px;
            border-top: 1px solid #eee;
            color: #7f8c8d;
            font-size: 13px;
        }}
        @media (max-width: 768px) {{
            .container {{
                padding: 15px;
            }}
            .article-title {{
                font-size: 15px;
            }}
            .article-summary {{
                font-size: 13px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📰 每日新闻导览</h1>
            <div class="meta-info">
                📅 日期: {current_date} | 🕐 生成时间: {current_time}
            </div>
        </header>
        
        <div class="summary">
            <h2>🎯 今日导览摘要</h2>
            <p>{daily_summary}</p>
        </div>
        
        """
        
        # 显示文章（按分类）
        has_content = False
        for category, count in category_article_counts:
            articles = self.articles_by_category[category]
            if articles:
                has_content = True
                html_content += f"""
        <div class="category">
            <h2>📂 {category} ({count}篇)</h2>
                """
                
                for i, article in enumerate(articles, 1):
                    clean_title = article['title'].strip()
                    if len(clean_title) > 70:
                        clean_title = clean_title[:70] + "..."
                    
                    html_content += f"""
            <div class="article-item">
                <div class="article-title">{i}. <a href="{article['url']}" target="_blank">{clean_title}</a></div>
                """
                    
                    if article.get('publish_date'):
                        # 简化日期显示
                        pub_date_str = str(article['publish_date'])
                        if len(pub_date_str) > 16:
                            pub_date_str = pub_date_str[:16]
                        html_content += f'<div class="article-meta">🕐 发布时间: {pub_date_str} | 📰 来源: {article["source"]}</div>\n'
                    else:
                        html_content += f'<div class="article-meta">📰 来源: {article["source"]}</div>\n'
                    
                    # 显示摘要（确保摘要不为空）
                    summary_text = article.get('summary', '').strip()
                    if summary_text and summary_text != "暂无摘要" and len(summary_text) > 10:
                        # 清理HTML标签
                        clean_summary = re.sub('<[^<]+?>', '', summary_text)
                        if len(clean_summary) > 200:
                            clean_summary = clean_summary[:200] + "..."
                        html_content += f'<div class="article-summary">📝 {clean_summary}</div>\n'
                    elif summary_text == "暂无摘要":
                        html_content += f'<div class="article-summary">📝 暂无摘要</div>\n'
                    
                    html_content += '            </div>\n'
                
                html_content += '        </div>\n'
        
        if not has_content:
            html_content += """
        <div class="category">
            <h2>⚠️ 暂无相关新闻</h2>
            <p>当前时间段内未找到符合关键词分类的新闻。</p>
        </div>
            """
        
        # 统计信息
        total_articles = sum(len(articles) for articles in self.articles_by_category.values())
        html_content += f"""
        <div class="stats">
            <h2>📊 详细统计</h2>
            <p><strong>总文章数:</strong> {total_articles}</p>
            <p><strong>涉及分类:</strong> {len([cat for cat, count in category_article_counts if count > 0])}</p>
            <p><strong>处理新闻源:</strong> {len(self.rss_sources)}</p>
            """
        
        for category, count in category_article_counts:
            if count > 0:
                html_content += f"<p>- {category}: {count}篇</p>\n"
        
        html_content += """
        </div>
        
        <footer>
            <p>📊 新闻日报自动生成 | 🕐 生成时间: """ + current_time + """ | 🤖 Powered by DeepSeek AI 大模型</p>
        </footer>
    </div>
</body>
</html>"""
        
        return html_content

class EmailSender:
    """邮件发送器"""
    
    @staticmethod
    def send_html_email(html_content: str, subject: str = None, config: dict = None) -> bool:
        """发送HTML邮件"""
        if not config:
            config = EMAIL_CONFIG
        
        required_fields = ['sender_email', 'sender_password', 'receiver_email']
        if not all(config.get(field) for field in required_fields):
            logger.error("❌ 邮件配置不完整")
            return False
        
        if not subject:
            subject = f"每日新闻导览-{datetime.now().strftime('%Y-%m-%d')}"
        
        try:
            # 创建邮件对象
            msg = MIMEMultipart('alternative')
            msg['From'] = config['sender_email']
            msg['To'] = config['receiver_email']
            msg['Subject'] = Header(subject, 'utf-8')
            
            # 添加HTML内容
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)
            
            # 连接SMTP服务器并发送
            server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
            server.starttls()
            server.login(config['sender_email'], config['sender_password'])
            server.send_message(msg)
            server.quit()
            
            logger.info("✅ 邮件发送成功！")
            return True
            
        except Exception as e:
            logger.error(f"❌ 邮件发送失败: {e}")
            return False

def main():
    """主函数"""
    logger.info("🚀 开始新闻日报任务...")
    
    # 从环境变量获取配置
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    SENDER_EMAIL = os.getenv('SENDER_EMAIL')
    SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')
    RECEIVER_EMAIL = os.getenv('RECEIVER_EMAIL')
    
    # 验证必要配置
    if not DEEPSEEK_API_KEY:
        logger.error("❌ 错误：必须设置 DEEPSEEK_API_KEY 环境变量！")
        logger.error("请在 GitHub Secrets 中添加 DEEPSEEK_API_KEY")
        sys.exit(1)
    
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL]):
        logger.error("❌ 请设置完整的邮件配置环境变量")
        sys.exit(1)
    
    # 更新邮件配置
    global EMAIL_CONFIG
    EMAIL_CONFIG.update({
        'sender_email': SENDER_EMAIL,
        'sender_password': SENDER_PASSWORD,
        'receiver_email': RECEIVER_EMAIL,
    })
    
    try:
        # 创建新闻抓取器（强制使用DeepSeek）
        logger.info("🔧 初始化 DeepSeek 大模型客户端...")
        scraper = EnhancedNewsScraper(deepseek_api_key=DEEPSEEK_API_KEY)
        
        # 开始抓取新闻
        logger.info("🌐 开始抓取新闻...")
        scraper.scrape_news()
        
        # 显示统计信息
        total_articles = sum(len(articles) for articles in scraper.articles_by_category.values())
        logger.info(f"📊 抓取统计 - 总文章数: {total_articles}")
        for category, articles in scraper.articles_by_category.items():
            if articles:
                logger.info(f"   📂 {category}: {len(articles)}篇")
        
        # 生成HTML报告（强制使用DeepSeek生成摘要）
        html_content = scraper.generate_html_report()
        logger.info("🎉 新闻日报生成完成!")
        
        # 保存HTML文件（用于调试）
        with open('/tmp/news_report.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info("💾 HTML报告已保存到 /tmp/news_report.html")
        
        # 发送邮件
        email_sent = EmailSender.send_html_email(
            html_content=html_content,
            subject=f"每日新闻导览-{datetime.now().strftime('%Y-%m-%d')} - DeepSeek AI 生成",
            config=EMAIL_CONFIG
        )
        
        if email_sent:
            logger.info("📧 邮件发送成功！")
        else:
            logger.error("📧 邮件发送失败！")
            
    except Exception as e:
        logger.error(f"❌ 执行过程中出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
