import newspaper
from datetime import datetime
import time
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import sys

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

class NewsScraper:
    def __init__(self, deepseek_api_key: str = None):
        # 新闻源配置
        self.news_sources = [
            'https://www.36kr.com',
            'https://www.pingwest.com',
            'https://www.jiqizhixin.com',
            'https://www.wired.com',
            'https://techcrunch.com',
        ]
        
        # 分类配置
        self.categories = {
            '科技': ['technology', 'tech', '科技', '数码', '互联网', '软件', '硬件'],
            'AI': ['ai', 'artificial intelligence', '人工智能', '机器学习', '深度学习', '算法'],
            '医疗': ['health', 'medical', '医疗', '健康', '医院', '疾病'],
        }
        
        # 存储结果
        self.articles_by_category = {category: [] for category in self.categories.keys()}
        self.processed_urls = set()
        
        # 初始化 DeepSeek 客户端
        self.deepseek_client = None
        if deepseek_api_key:
            try:
                self.deepseek_client = OpenAI(
                    api_key=deepseek_api_key,
                    base_url="https://api.deepseek.com"
                )
                logger.info("✅ DeepSeek API 客户端初始化成功")
            except Exception as e:
                logger.error(f"❌ DeepSeek API 客户端初始化失败: {e}")
    
    def get_news_source(self, source_url: str) -> newspaper.Source:
        """获取新闻源"""
        try:
            config = {
                'memoize_articles': False,
                'request_timeout': 15,
                'browser_user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            source = newspaper.build(source_url, **config)
            logger.info(f"✅ 成功加载新闻源: {source_url} (文章数: {len(source.articles)})")
            return source
        except Exception as e:
            logger.error(f"❌ 加载新闻源失败 {source_url}: {e}")
            return None
    
    def is_article_relevant(self, article) -> tuple:
        """检查文章是否包含关键词"""
        try:
            if article.url in self.processed_urls:
                return False, []
            
            self.processed_urls.add(article.url)
            
            article.download()
            if not article.download_state == 2:
                return False, []
                
            article.parse()
            
            title = article.title.lower() if article.title else ""
            text = article.text.lower() if article.text else ""
            content = title + " " + text[:1000]
            
            if len(content) < 30:
                return False, []
            
            relevant_categories = []
            
            for category, keywords in self.categories.items():
                match_score = 0
                for keyword in keywords:
                    if keyword.lower() in content:
                        match_score += 1
                        if keyword.lower() in title:
                            match_score += 2
                
                threshold = 1 if keyword.lower() in title else 2
                if match_score >= threshold:
                    relevant_categories.append(category)
            
            return len(relevant_categories) > 0, relevant_categories
            
        except Exception as e:
            logger.debug(f"处理文章时出错: {e}")
            return False, []
    
    def scrape_news(self, max_articles_per_source: int = 6):
        """抓取新闻"""
        successful_sources = 0
        total_processed = 0
        
        for source_url in self.news_sources:
            logger.info(f"📡 正在处理新闻源: {source_url}")
            
            source = self.get_news_source(source_url)
            if not source or len(source.articles) == 0:
                logger.warning(f"⚠️ 新闻源 {source_url} 没有可处理的文章")
                continue
            
            articles_to_process = source.articles[:max_articles_per_source]
            processed_count = 0
            
            for article in articles_to_process:
                try:
                    is_relevant, categories = self.is_article_relevant(article)
                    
                    if is_relevant:
                        article_data = {
                            'title': article.title.strip() if article.title else "无标题",
                            'url': article.url,
                            'publish_date': article.publish_date,
                            'summary': (article.summary[:150] + "...") if article.summary else ""
                        }
                        
                        for category in categories:
                            if not any(a['url'] == article.url for a in self.articles_by_category[category]):
                                self.articles_by_category[category].append(article_data)
                        
                        logger.info(f"🎯 找到相关文章: {article.title[:50]}...")
                        processed_count += 1
                        total_processed += 1                     
                    time.sleep(0.2)
                    
                except Exception as e:
                    logger.debug(f"处理文章时出错 {article.url}: {e}")
                    continue
            
            if processed_count > 0:
                successful_sources += 1
            logger.info(f"📊 从 {source_url} 处理了 {processed_count} 篇相关文章")
        
        logger.info(f"📈 总结: 处理了 {successful_sources} 个新闻源，共找到 {total_processed} 篇相关文章")
    
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
    
    def generate_daily_summary(self) -> str:
        """使用 DeepSeek 生成今日新闻摘要"""
        if not self.deepseek_client:
            return "⚠️ 未配置 DeepSeek API，无法生成智能摘要。"
        
        try:
            all_titles = []
            category_stats = {}
            
            for category, articles in self.articles_by_category.items():
                if articles:
                    category_stats[category] = len(articles)
                    for article in articles[:6]:
                        all_titles.append(f"[{category}] {article['title']}")
            
            if not all_titles:
                return "📰 今日暂无相关新闻内容。"
            
            titles_text = "\n".join(all_titles[:30])
            stats_text = ", ".join([f"{cat}:{count}篇" for cat, count in category_stats.items()])
            
            prompt = f"""
            请基于以下今日新闻标题，生成一段300-400字的中文摘要。要求：
            1. 不要机械复述标题，要进行概括与串联
            2. 提炼出当日新闻的主要趋势、关注焦点
            3. 风格自然流畅，具有整体感
            4. 突出最重要的几个主题方向
            
            今日新闻统计：{stats_text}
            
            新闻标题列表：
            {titles_text}
            
            请以"今日导览摘要："开头，直接输出摘要内容。
            """
            
            logger.info("🤖 正在调用 DeepSeek 生成智能摘要...")
            
            response = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位专业的新闻分析师，擅长总结和分析新闻趋势。"},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=0.7,
                max_tokens=600
            )
            
            summary = response.choices[0].message.content.strip()
            if not summary.startswith("今日导览摘要："):
                summary = "今日导览摘要：" + summary
            
            logger.info("✅ DeepSeek 摘要生成成功")
            return summary
            
        except Exception as e:
            error_msg = f"❌ DeepSeek 摘要生成失败: {e}"
            logger.error(error_msg)
            return "今日导览摘要：由于系统原因，暂无法生成智能摘要。"
    
    def generate_html_report(self) -> str:
        """生成HTML格式的日报"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 生成摘要
        daily_summary = self.generate_daily_summary()
        
        # 去重
        self.remove_duplicates()
        
        # 按文章数量排序分类
        category_article_counts = [(cat, len(articles)) for cat, articles in self.articles_by_category.items() if articles]
        category_article_counts.sort(key=lambda x: x[1], reverse=True)
        
        # HTML 模板
        html_content = f"""
<!DOCTYPE html>
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
            max-width: 800px;
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
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid #ffc107;
        }}
        .category {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .category h2 {{
            margin-top: 0;
            color: #2c3e50;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
        }}
        .article-item {{
            margin: 15px 0;
            padding: 15px;
            background: white;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .article-title {{
            font-size: 16px;
            font-weight: 600;
            margin: 0 0 8px 0;
        }}
        .article-title a {{
            color: #3498db;
            text-decoration: none;
        }}
        .article-title a:hover {{
            text-decoration: underline;
        }}
        .article-meta {{
            font-size: 12px;
            color: #7f8c8d;
            margin: 5px 0;
        }}
        .article-summary {{
            font-size: 13px;
            color: #555;
            margin: 8px 0 0 0;
            line-height: 1.5;
        }}
        .stats {{
            background-color: #e8f4f8;
            padding: 15px;
            border-radius: 8px;
            margin-top: 30px;
        }}
        footer {{
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #7f8c8d;
            font-size: 12px;
        }}
        @media (max-width: 600px) {{
            .container {{
                padding: 15px;
            }}
            .article-title {{
                font-size: 14px;
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
        
        has_content = False
        for category, count in category_article_counts:
            articles = self.articles_by_category[category]
            if articles:
                has_content = True
                html_content += f"""
        <div class="category">
            <h2>�? {category} ({count}篇)</h2>
                """
                
                for i, article in enumerate(articles, 1):
                    clean_title = article['title'].replace('[', '').replace(']', '').strip()
                    if len(clean_title) > 60:
                        clean_title = clean_title[:60] + "..."
                    
                    html_content += f"""
            <div class="article-item">
                <div class="article-title">{i}. <a href="{article['url']}" target="_blank">{clean_title}</a></div>
                """
                    
                    if article.get('publish_date'):
                        pub_date = article['publish_date']
                        if isinstance(pub_date, str):
                            html_content += f'<div class="article-meta">🕐 发布时间: {pub_date}</div>\n'
                        elif hasattr(pub_date, 'strftime'):
                            html_content += f'<div class="article-meta">🕐 发布时间: {pub_date.strftime("%Y-%m-%d %H:%M")}</div>\n'
                    
                    if article.get('summary') and len(article['summary']) > 10:
                        html_content += f'<div class="article-summary">📝 摘要: {article["summary"]}</div>\n'
                    
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
            <p>- 总文章数: {total_articles}</p>
            <p>- 涉及分类: {len([cat for cat, count in category_article_counts if count > 0])}</p>
            <p>- 处理新闻源: {len(self.news_sources)}</p>
        </div>
        
        <footer>
            <p>📊 新闻日报自动生成 | 🕐 生成时间: {current_time} | 🤖 Powered by DeepSeek AI</p>
        </footer>
    </div>
</body>
</html>
        """
        
        return html_content

class EmailSender:
    """邮件发送器"""
    
    @staticmethod
    def send_html_email(html_content: str, subject: str = None, config: dict = None) -> bool:
        """发送HTML邮件"""
        if not config:
            config = EMAIL_CONFIG
        
        if not all([config['sender_email'], config['sender_password'], config['receiver_email']]):
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
    
    if not all([DEEPSEEK_API_KEY, SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL]):
        logger.error("❌ 环境变量配置不完整，请检查 GitHub Secrets 设置")
        sys.exit(1)
    
    # 更新邮件配置
    global EMAIL_CONFIG
    EMAIL_CONFIG.update({
        'sender_email': SENDER_EMAIL,
        'sender_password': SENDER_PASSWORD,
        'receiver_email': RECEIVER_EMAIL,
    })
    
    try:
        # 创建新闻抓取器
        scraper = NewsScraper(deepseek_api_key=DEEPSEEK_API_KEY)
        
        # 开始抓取新闻
        logger.info("🌐 开始抓取新闻...")
        scraper.scrape_news(max_articles_per_source=5)
        
        # 生成HTML报告
        html_content = scraper.generate_html_report()
        logger.info("🎉 新闻日报生成完成!")
        
        # 发送邮件
        email_sent = EmailSender.send_html_email(
            html_content=html_content,
            subject=f"每日新闻导览-{datetime.now().strftime('%Y-%m-%d')}",
            config=EMAIL_CONFIG
        )
        
        if email_sent:
            logger.info("📧 邮件发送成功！")
        else:
            logger.error("📧 邮件发送失败！")
            
    except Exception as e:
        logger.error(f"❌ 执行过程中出错: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
