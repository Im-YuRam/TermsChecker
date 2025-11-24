import os
import time
import json
import re
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# .envファイルの読み込み
load_dotenv()

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------
# APIキーの設定とデモモードの判定
# ---------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
IS_DEMO_MODE = False

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        print("✅ Gemini APIキーが設定されました。通常モードで動作します。")
    except Exception as e:
        print(f"⚠️ APIキーの設定中にエラーが発生しました: {e}")
        IS_DEMO_MODE = True
else:
    print("⚠️ GEMINI_API_KEYが見つかりません。デモモード（サンプル結果表示）で動作します。")
    IS_DEMO_MODE = True

# ---------------------------------------------------------
# サンプルデータ（デモモード用）
# ---------------------------------------------------------
# ---------------------------------------------------------
# サンプルデータ（デモモード用：Google利用規約の分析結果）
# ---------------------------------------------------------
SAMPLE_RESULT = {
    "overall_evaluation": {
        "risk_level": "中",
        "reason": "世界的な標準規約であり、法的な完成度は非常に高いですが、ユーザーのコンテンツに対する広範なライセンス付与や、運営側の責任を限定する条項が含まれており、消費者保護の観点からは注意が必要な点がいくつか存在します。"
    },
    "detailed_analysis": [
        {
            "category": "個人情報の取り扱い",
            "is_safe": True,
            "summary": "プライバシーポリシーへの明確な参照があり、データ利用の透明性は確保されています。",
            "issues": []
        },
        {
            "category": "免責事項",
            "is_safe": False,
            "summary": "法律で認められる範囲内で、運営側の保証を排除し、責任を限定する条項が含まれています。",
            "issues": [
                {
                    "clause": "法域によっては、商品性、特定の目的への適合性、権利侵害がないことの黙示保証など、一定の保証が認められる場合があります。法律で認められる範囲内で、Google は、すべての保証を排除します。",
                    "risk": "サービスの品質や適合性について、明示されていない限り一切の保証を行わないとしており、ユーザーが不利益を被る可能性があります。"
                },
                {
                    "clause": "法律で認められる範囲内で、Google、そのサプライヤー、およびディストリビューターの魚...（中略）...損害賠償の責任を負わないものとします。",
                    "risk": "間接的な損害や逸失利益について、Googleが責任を負わないことが明記されており、トラブル時の補償が限定されるリスクがあります。"
                }
            ]
        },
        {
            "category": "規約の変更",
            "is_safe": False,
            "summary": "合理的な通知を行うとはされていますが、運営側の判断で規約やサービス内容を変更できる権限が留保されています。",
            "issues": [
                {
                    "clause": "Google は、本サービスに変更を加える場合、...（中略）...合理的な事前の通知を行うものとします。ただし、不正利用の防止、法的要件への対応、またはセキュリティや運用上の問題への対処を目的とする場合を除きます。",
                    "risk": "緊急時やセキュリティ対応を理由に、事前の通知なくサービス内容や条件が変更される可能性が残されています。"
                }
            ]
        },
        {
            "category": "禁止事項とペナルティ",
            "is_safe": True,
            "summary": "不正利用や妨害行為などが禁止されていますが、一般的なWebサービスの範囲内であり、不当に厳しい内容ではありません。",
            "issues": []
        },
        {
            "category": "知的財産権",
            "is_safe": False,
            "summary": "ユーザーはコンテンツの所有権を保持しますが、Googleに対して非常に広範な利用許諾（ライセンス）を与える構成になっています。",
            "issues": [
                {
                    "clause": "ユーザーは、そのコンテンツについて保有する知的財産権を引き続き保持します。...（中略）...ユーザーは Google に対し、そのコンテンツを使用、ホスト、保存、複製、変更、派生著作物の作成...（中略）...を行うための全世界的なライセンスを付与することになります。",
                    "risk": "著作権はユーザーに残りますが、Googleはサービスの運営・改善・宣伝のために、ユーザーのコンテンツをほぼ自由に利用できる強力な権利を持つことになります。"
                }
            ]
        }
    ]
}

# ---------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------
def extract_text_from_url(url: str) -> str | None:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text(separator='\n', strip=True)
    except requests.exceptions.RequestException as e:
        print(f"URLへのアクセスに失敗しました: {e}")
        return None

def split_text(text: str, max_chars: int = 8000) -> list[str]:
    chunks = []
    while len(text) > max_chars:
        split_pos = text.rfind('。', 0, max_chars)
        if split_pos == -1: split_pos = max_chars
        else: split_pos += 1
        chunks.append(text[:split_pos])
        text = text[split_pos:]
    chunks.append(text)
    return chunks

def send_to_gemini(prompt: str) -> str:
    # デモモードならAPIを呼ばない
    if IS_DEMO_MODE:
        return "{}" 

    try:
        # モデル指定 (gemini-2.0-flashなど、利用可能な最新モデルに合わせてください)
        model = genai.GenerativeModel('gemini-1.5-flash') 
        response = model.generate_content(prompt)
        match = re.search(r'```json\s*([\s\S]*?)\s*```', response.text)
        if match:
            return match.group(1).strip()
        return response.text
    except Exception as e:
        # エラー時はJSON形式のエラーメッセージを文字列で返す
        return json.dumps({"error": f"Gemini APIとの通信中にエラー: {e}"})

# ---------------------------------------------------------
# ルーティング処理
# ---------------------------------------------------------
@app.route('/analyze', methods=['POST'])
def handle_analysis_request():
    # 1. デモモード（APIキーなし）の場合の処理
    if IS_DEMO_MODE:
        print("【デモモード】サンプルデータを返却します。")
        # 実際の処理をスキップしてサンプル結果を即座に返す
        # 少し通信している雰囲気を出すためにウェイトを入れる（任意）
        time.sleep(1.5) 
        return jsonify(SAMPLE_RESULT)

    # 2. 通常モード（APIキーあり）の処理
    data = request.get_json()
    if not data or 'terms_url' not in data:
        return jsonify({'error': 'リクエストに "terms_url" が含まれていません。'}), 400

    url = data['terms_url']
    if not url.strip(): return jsonify({'error': 'URLが空です。'}), 400
    
    print(f"URLからテキストを抽出します: {url}")
    full_text = extract_text_from_url(url)
    if full_text is None: return jsonify({'error': 'URLからテキストを抽出できませんでした。'}), 400
    
    print(f"抽出したテキストの文字数: {len(full_text)}")
    text_chunks = split_text(full_text)
    print(f"{len(text_chunks)}個のチャンクに分割しました。")
    
    all_issues = []

    # --- 各チャンクの解析 ---
    for i, chunk in enumerate(text_chunks):
        print(f"チャンク {i + 1}/{len(text_chunks)} の問題点を抽出中...")
        part_prompt = f"""
        あなたは消費者保護専門の弁護士です。以下の利用規約のテキスト断片から、消費者にとって潜在的に不利または危険な条項のみを抽出し、以下のJSON形式の配列で出力してください。
        問題点が見つからない場合は空の配列 `[]` を出力してください。説明文は一切不要です。

        [
          {{
            "clause": "該当する条文の正確な引用",
            "risk": "その条文がなぜ問題なのか、具体的なリスクの解説"
          }}
        ]

        --- テキスト断片 ---
        {chunk}
        """
        part_result_str = send_to_gemini(part_prompt)
        try:
            issues = json.loads(part_result_str)
            # エラーメッセージが返ってきている場合への対処
            if isinstance(issues, dict) and "error" in issues:
                print(f"APIエラー: {issues['error']}")
                continue
            if isinstance(issues, list):
                all_issues.extend(issues)
        except json.JSONDecodeError:
            print(f"チャンク {i + 1} の解析でJSONデコードエラーが発生しました。")
        
        if i < len(text_chunks) - 1: time.sleep(2)

    print("全ての問題点抽出が完了。最終レポートを作成します...")
    
    # --- 最終レポート作成 ---
    issues_json_str = json.dumps(all_issues, indent=2, ensure_ascii=False)
    final_prompt = f"""
    あなたは消費者保護専門の弁護士です。以下のJSON形式の問題点リストをレビューし、最終的な分析レポートを生成してください。
    レポートは、必ず以下の厳密なJSON形式で出力してください。説明文や```jsonマークダウンは一切不要です。

    {{
      "overall_evaluation": {{
        "risk_level": "高か中か低",
        "reason": "総合評価の理由についての簡潔な解説"
      }},
      "detailed_analysis": [
        {{
          "category": "個人情報の取り扱い",
          "is_safe": trueかfalse,
          "summary": "このカテゴリの要約（問題がない場合はその旨を記載）",
          "issues": [
            {{
              "clause": "関連する条文の引用",
              "risk": "そのリスクの解説"
            }}
          ]
        }},
        {{
          "category": "免責事項",
          "is_safe": trueかfalse,
          "summary": "このカテゴリの要約",
          "issues": []
        }},
        {{
          "category": "規約の変更",
          "is_safe": trueかfalse,
          "summary": "このカテゴリの要約",
          "issues": []
        }},
        {{
          "category": "禁止事項とペナルティ",
          "is_safe": trueかfalse,
          "summary": "このカテゴリの要約",
          "issues": []
        }},
        {{
          "category": "知的財産権",
          "is_safe": trueかfalse,
          "summary": "このカテゴリの要約",
          "issues": []
        }}
      ]
    }}

    --- 分析対象の問題点リスト ---
    {issues_json_str}
    """
    
    final_report_str = send_to_gemini(final_prompt)
    try:
        final_report_json = json.loads(final_report_str)
        print("全文分析が完了しました。")
        return jsonify(final_report_json)
    except json.JSONDecodeError:
        print("最終レポートの解析でJSONデコードエラーが発生しました。")
        return jsonify({"error": "最終レポートの生成に失敗しました。AIからの応答が不正なJSON形式です。"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)