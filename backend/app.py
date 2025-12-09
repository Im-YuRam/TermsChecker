import os
import json
import time
import google.generativeai as genai
import trafilatura
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- 設定とデモモード判定 ---
API_KEY = os.environ.get("GEMINI_API_KEY")
IS_DEMO = False

if not API_KEY:
    print("注意: GEMINI_API_KEY が設定されていません。デモモードで起動します。")
    IS_DEMO = True
else:
    try:
        genai.configure(api_key=API_KEY)
    except Exception as e:
        print(f"APIキー設定エラー: {e}")
        IS_DEMO = True

MODEL_NAME = 'gemini-2.5-flash' 
MAX_WORKERS = 4
GOOGLE_TOS_URL = "https://policies.google.com/terms?hl=ja" # デモ用URL

# --- Google利用規約のモックデータ (デモ用) ---
GOOGLE_TOS_MOCK_DATA = {
    "is_demo": True,
    "overall_evaluation": {
        "risk_level": "中",
        "reason": "広範なデータ収集権限と、運営側の裁量によるアカウント停止権限が含まれていますが、一般的なプラットフォーマーとしては標準的な内容です。"
    },
    "detailed_analysis": [
        {
            "category": "個人情報の取り扱い",
            "is_safe": False,
            "summary": "サービス向上のため、検索履歴、動画視聴履歴、位置情報など、極めて広範囲なユーザーデータを収集・利用することが明記されています。",
            "issues": [
                {
                    "clause": "当社は、お客様が当社のサービスを利用する際に提供するコンテンツ、通信、その他の情報を収集します。",
                    "risk": "収集される情報の範囲が非常に広く、プロファイリングや広告配信に利用される可能性があります。"
                }
            ]
        },
        {
            "category": "免責事項",
            "is_safe": True,
            "summary": "法的に認められる範囲での保証の否認が含まれていますが、重大な過失がある場合の責任までは否定していません。",
            "issues": []
        },
        {
            "category": "規約の変更",
            "is_safe": False,
            "summary": "ユーザーへの事前の通知を行った上で規約を変更する場合があるとされていますが、重要な変更であってもサービス継続により同意とみなされる可能性があります。",
            "issues": [
                {
                    "clause": "当社は、本規約を更新することがあります。重要な変更については事前に通知するよう努めます。",
                    "risk": "「努めます」という表現に留まっており、確実な事前通知が保証されない可能性があります。"
                }
            ]
        },
        {
            "category": "禁止事項とペナルティ",
            "is_safe": False,
            "summary": "規約違反があった場合、事前の通知なくアカウントへのアクセスを停止できる強力な権限をGoogleが有しています。",
            "issues": [
                {
                    "clause": "お客様が本規約に違反した場合、当社はサービスの提供を停止または終了することができます。",
                    "risk": "Googleアカウントが停止されると、GmailやGoogle Driveなど関連サービス全てにアクセスできなくなる甚大な影響があります。"
                }
            ]
        },
        {
            "category": "知的財産権",
            "is_safe": True,
            "summary": "ユーザーが投稿したコンテンツの著作権はユーザーに帰属しますが、Googleがサービス運営のためにそれらを使用・配信するライセンスを付与する形になっています。",
            "issues": []
        },
        {
            "category": "その他",
            "is_safe": True,
            "summary": "紛争時の準拠法や管轄裁判所について規定されています。",
            "issues": []
        }
    ]
}

def extract_text_from_url(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None: return None
        return trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    except Exception as e:
        print(f"Extraction Error: {e}")
        return None

def split_text(text: str, max_chars: int = 15000) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        split_pos = text.rfind('。', 0, max_chars)
        if split_pos == -1: split_pos = max_chars
        else: split_pos += 1
        chunks.append(text[:split_pos])
        text = text[split_pos:]
    chunks.append(text)
    return chunks

def analyze_chunk_with_gemini(chunk: str, chunk_id: int) -> list:
    if IS_DEMO: return []
    
    prompt = f"""
    あなたは消費者保護専門の弁護士です。以下の利用規約のテキスト断片から、消費者にとって不利・危険・不透明な条項を抽出してください。
    出力はJSON配列のみで返してください。問題がない場合は空の配列 `[]` を返してください。
    [スキーマ] [ {{ "clause": "条文引用", "risk": "リスク解説" }} ]
    --- テキスト ---
    {chunk}
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except Exception as e:
        print(f"Chunk {chunk_id} Error: {e}")
        return []


@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        'is_demo': IS_DEMO,
        'default_url': GOOGLE_TOS_URL if IS_DEMO else ""
    })

@app.route('/analyze', methods=['POST'])
def handle_analysis_request():
    data = request.get_json()
    
    if IS_DEMO:
        print("デモモードでリクエストを処理します。")
        time.sleep(3) # 演出のためのウェイト
        return jsonify(GOOGLE_TOS_MOCK_DATA)

    if not data or 'terms_url' not in data:
        return jsonify({'error': 'URLが指定されていません。'}), 400

    url = data['terms_url']
    print(f"Processing: {url}")
    
    full_text = extract_text_from_url(url)
    if not full_text:
        return jsonify({'error': 'URLからテキストを取得できませんでした。アクセスできないサイトの可能性があります。'}), 400
    
    text_chunks = split_text(full_text)
    all_issues = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_chunk = {
            executor.submit(analyze_chunk_with_gemini, chunk, i): i 
            for i, chunk in enumerate(text_chunks)
        }
        for future in as_completed(future_to_chunk):
            try:
                issues = future.result()
                if isinstance(issues, list): all_issues.extend(issues)
            except Exception: pass

    issues_json_str = json.dumps(all_issues, indent=2, ensure_ascii=False)
    
    final_prompt = f"""
    あなたは消費者保護のプロフェッショナルです。
    以下のJSONデータは、利用規約から抽出された「懸念される条項」のリストです。
    これらを分析し、**以下の指定された6つのカテゴリ**に分類して整理した最終レポートを作成してください。

    【指定カテゴリ】
    1. 個人情報の取り扱い
    2. 免責事項
    3. 規約の変更
    4. 禁止事項とペナルティ
    5. 知的財産権
    6. その他

    各カテゴリについて、問題がある場合は `is_safe: false` とし、リスクを詳細に記述してください。
    特に問題が見当たらないカテゴリは `is_safe: true` とし、issuesは空にしてください。

    出力フォーマット（JSON形式）:
    {{
      "overall_evaluation": {{
        "risk_level": "高 / 中 / 低",
        "reason": "総合的なリスク評価の理由"
      }},
      "detailed_analysis": [
        {{
          "category": "カテゴリ名",
          "is_safe": true/false,
          "summary": "要約",
          "issues": [ {{ "clause": "引用", "risk": "解説" }} ]
        }}
      ]
    }}
    --- データ ---
    {issues_json_str}
    """

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        final_response = model.generate_content(final_prompt, generation_config={"response_mime_type": "application/json"})
        return jsonify(json.loads(final_response.text))
    except Exception as e:
        print(f"Final Report Error Details: {e}")
        return jsonify({"error": f"レポート生成中にエラーが発生しました: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)