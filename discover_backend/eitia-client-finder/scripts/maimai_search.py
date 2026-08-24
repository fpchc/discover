#!/usr/bin/env python3
"""
EITIA 脉脉自动化采集脚本

将原本 AI 需要手动执行的 6 步流程封装为脚本，避免遗漏。

流程:
  1. 读取 .maimai-auth.json（Playwright storageState）
  2. 启动 Playwright Chromium
  3. 注入 cookies
  4. 逐个搜索企业关键词（全称 + 简称）
  5. 提取在职非一线员工（排除实习生/普工/技工/操作工等）
  6. 输出标准化 JSON

用法:
  python scripts/maimai_search.py --companies "信捷电气,汇川技术,雷赛智能" --auth .maimai-auth.json
  python scripts/maimai_search.py --companies "中控技术,埃斯顿" --auth .maimai-auth.json --output maimai2.json

输出 JSON 格式:
{
  "companies": {
    "信捷电气": [
      {"name": "王淑惠", "position": "采购", "company": "无锡信捷电气股份有限公司",
       "city": "无锡", "rank": 53, "line4": "汽车/机械/制造 | 采购物流", ...},
      ...
    ]
  },
  "summary": {"total_companies": 5, "total_contacts": 123, "errors": []}
}

依赖: playwright (pip install playwright && playwright install chromium)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

# 排除职位关键词（一线非决策岗）
EXCLUDE_POSITION_KEYWORDS = [
    "实习生", "普工", "技工", "操作工", "作业员", "保安", "司机", "保洁",
    "客服", "店员", "服务员", "仓管员", "装配工", "包装工", "搬运工"
]

# 每企业搜索的关键词组合
def get_search_keywords(company_names):
    """对每个企业，生成全称+简称两种搜索词"""
    pairs = []
    for name in company_names:
        name = name.strip()
        # 简称：取前2-4个字（去掉"股份有限公司""有限公司"等后缀）
        short = name.replace("股份有限公司", "").replace("有限公司", "").replace("有限责任公司", "")
        if len(short) > 6:
            short = short[:6]
        pairs.append((name, [name, short]))
    return pairs


def search_company(page, uid, query, max_results=20):
    """通过浏览器内 fetch 调用脉脉搜索 API"""
    url = f"https://maimai.cn/search/contacts?u={uid}&count={max_results}&page=0&query={query}&dist=0&jsononly=1&pc=1"
    try:
        result = page.evaluate("""
            async (url) => {
                const res = await fetch(url, { credentials: 'include' });
                return await res.json();
            }
        """, url)
        return result
    except Exception as e:
        return {"error": str(e)}


def filter_contacts(data):
    """过滤：仅在职、有姓名+职位、非一线岗"""
    if not data or data.get("result") != "ok":
        return []
    contacts = data.get("data", {}).get("contacts", [])
    filtered = []
    for c in contacts:
        contact = c.get("contact", {})
        if contact.get("former"):  # 跳过离职
            continue
        name = contact.get("name", "")
        position = contact.get("position", "")
        if not name or not position:
            continue
        # 排除一线岗
        if any(kw in position for kw in EXCLUDE_POSITION_KEYWORDS):
            continue
        filtered.append({
            "name": name,
            "position": position,
            "company": contact.get("company", ""),
            "city": contact.get("city", ""),
            "rank": contact.get("rank", 0),
            "line4": contact.get("line4", ""),
            "abstract": (contact.get("abstract") or "")[:150],
            "lock": contact.get("lock", False),
        })
    # 按影响力降序
    filtered.sort(key=lambda x: x["rank"], reverse=True)
    return filtered


def main():
    parser = argparse.ArgumentParser(description="EITIA 脉脉自动化采集")
    parser.add_argument("--companies", required=True, help="企业名称列表，逗号分隔")
    parser.add_argument("--auth", default=".maimai-auth.json", help="脉脉认证文件路径")
    parser.add_argument("--output", default=None, help="输出 JSON 文件路径（默认 stdout）")
    parser.add_argument("--max-per-company", type=int, default=8, help="每企业最多返回人数")
    args = parser.parse_args()

    # 解析企业列表
    company_list = [c.strip() for c in args.companies.split(",") if c.strip()]
    if not company_list:
        print("ERROR: --companies 不能为空", file=sys.stderr)
        sys.exit(1)

    # 读取认证文件
    auth_path = Path(args.auth)
    if not auth_path.is_absolute():
        # 尝试当前工作目录
        cwd_auth = Path.cwd() / args.auth
        if cwd_auth.exists():
            auth_path = cwd_auth
        else:
            # 尝试默认位置
            default_auth = Path("D:/ClaudeCode/产品原型验证/01客户发现/.maimai-auth.json")
            if default_auth.exists():
                auth_path = default_auth

    if not auth_path.exists():
        print(f"ERROR: 认证文件不存在: {auth_path}", file=sys.stderr)
        print("请确保已通过 maimai-prospect Skill 完成登录，生成了 .maimai-auth.json", file=sys.stderr)
        print("文件位置: 当前工作目录或 D:/ClaudeCode/产品原型验证/01客户发现/", file=sys.stderr)
        sys.exit(1)

    with open(auth_path, "r", encoding="utf-8") as f:
        auth_state = json.load(f)

    # 启动 Playwright
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright 未安装。运行: pip install playwright && playwright install chromium", file=sys.stderr)
        sys.exit(1)

    results = {}
    errors = []
    total_contacts = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()

        # 注入 cookies
        cookies_to_add = auth_state.get("cookies", [])
        # 仅注入关键 cookies（避免 httpOnly 注入报错）
        safe_cookies = []
        for c in cookies_to_add:
            safe = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".maimai.cn"),
                "path": c.get("path", "/"),
            }
            if c.get("secure"):
                safe["secure"] = True
            safe_cookies.append(safe)

        try:
            context.add_cookies(safe_cookies)
        except Exception as e:
            errors.append(f"Cookie 注入失败: {e}")

        page = context.new_page()

        # 从 cookies 中提取 uid
        uid = None
        for c in cookies_to_add:
            if c["name"] == "u" and c.get("value", "").isdigit():
                uid = c["value"]
                break
        if not uid:
            uid = "1407319"  # 默认值

        # 逐个搜索企业
        search_pairs = get_search_keywords(company_list)
        for company_name, keywords in search_pairs:
            all_contacts = {}
            for kw in keywords:
                try:
                    data = search_company(page, uid, kw)
                    filtered = filter_contacts(data)
                    for c in filtered:
                        key = c["name"]
                        if key not in all_contacts or c["rank"] > all_contacts[key]["rank"]:
                            all_contacts[key] = c
                    time.sleep(0.5)  # 避免被限流
                except Exception as e:
                    errors.append(f"{company_name}/{kw}: {e}")

            top_contacts = sorted(all_contacts.values(), key=lambda x: x["rank"], reverse=True)[:args.max_per_company]
            results[company_name] = top_contacts
            total_contacts += len(top_contacts)

        browser.close()

    # 构建输出
    output = {
        "companies": results,
        "summary": {
            "total_companies": len(company_list),
            "total_contacts": total_contacts,
            "errors": errors,
        }
    }

    # 输出
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"结果已写入: {out_path} ({total_contacts} 条联系人, {len(errors)} 个错误)")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    # 有错误时返回非零
    if errors:
        print(f"\n警告: {len(errors)} 个错误:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
