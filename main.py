import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from supabase import create_client, Client
from openai import OpenAI

# 从 GitHub 的环境变量里读取钥匙
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TARGET_URL = os.environ.get("TARGET_URL") # 这是你手动输入的文章链接

if not all([SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, TARGET_URL]):
    print("❌ 错误：缺少必要的环境变量或文章链接")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 核心功能函数 ---
def fetch_article(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # 简单粗暴：抓取所有段落
        return "\n".join([p.text for p in soup.find_all('p')])[:8000]
    except Exception as e:
        print(f"抓取失败: {e}")
        return None

def get_deadline_analyst_id():
    # 查找或创建 Deadline 分析师
    res = supabase.table("analysts").select("id").eq("outlet", "Deadline").execute()
    if res.data: return res.data[0]['id']
    new = supabase.table("analysts").insert({"name":"Anthony","outlet":"Deadline"}).execute()
    return new.data[0]['id']

def ai_parse(text, movie_name):
    prompt = f"""
    从下文中提取电影《{movie_name}》的北美首周末票房预测。
    返回纯JSON格式: {{"min":数字(百万), "max":数字, "avg":数字}}。
    若无数据则全返回0。文本: {text}
    """
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    content = resp.choices[0].message.content.replace("```json","").replace("```","").strip()
    return json.loads(content)

# --- 主程序 ---
def main():
    print(f"🚀 开始处理链接: {TARGET_URL}")
    
    # 1. 找正在追踪的电影
    movies = supabase.table("movies").select("*").eq("status", "Tracking").execute().data
    if not movies:
        print("⚠️ 没有正在追踪 (Tracking) 的电影，请先在数据库添加电影")
        return

    analyst_id = get_deadline_analyst_id()
    
    # 2. 抓取文章
    content = fetch_article(TARGET_URL)
    if not content: return

    # 3. 遍历每部电影，问 AI 文章里有没有提到它
    for movie in movies:
        print(f"🔍 正在分析电影: {movie['title_en']}")
        data = ai_parse(content, movie['title_en'])
        
        if data['avg'] > 0:
            print(f"✅ 找到数据: {data}")
            # 计算倒计时
            release = datetime.strptime(movie['release_date'], "%Y-%m-%d").date()
            days = (release - datetime.now().date()).days
            
            # 写入数据库
            supabase.table("predictions").insert({
                "movie_id": movie['id'],
                "analyst_id": analyst_id,
                "scraped_date": str(datetime.now().date()),
                "days_to_release": days,
                "forecast_min": data['min'],
                "forecast_max": data['max'],
                "forecast_avg": data['avg']
            }).execute()
            print("💾 已保存到 Supabase")
        else:
            print("❌ 文章未提及该电影")

if __name__ == "__main__":
    main()
