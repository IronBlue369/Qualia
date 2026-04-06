#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_signature.py

Qualia Journal の全記事に署名ブロック (e. Tamaki) を一括で追加するスクリプト。

使い方:
  python apply_signature.py <リポジトリのルートディレクトリ>

  # デフォルトは dry-run (ファイルは書き換えない)
  python apply_signature.py .

  # 差分を見る
  python apply_signature.py . --diff

  # 実際に適用する
  python apply_signature.py . --apply

処理内容 (各記事の index.html に対して):
  1. CSSブロックの .note-box strong{...} の直後に .signature の2行を追加
  2. HTMLの <div class="note-box fade">...</div> の直後、
     <div class="tags fade">...</div> の直前に
     <div class="signature fade">e. Tamaki</div> を挿入

安全機構:
  - デフォルトで dry-run (書き換えない)
  - 既に適用済みのファイルはスキップ (冪等性)
  - CSSとHTMLの両方が見つからない場合は警告して触らない
  - 各ファイルの状態を ✓ / - / ⚠ / ✗ で報告
"""

import sys
import os
import re
import argparse
import difflib
from pathlib import Path

# ---------------------------------------------------------------------------
# 追加する内容
# ---------------------------------------------------------------------------

# CSS側に追加する2行 (.note-box strong{...} の直後に入れる)
CSS_ADDITION = (
    ".signature{margin:18px 0 0;text-align:right;font-family:'Playfair Display',serif;"
    "font-size:14px;font-style:italic;font-weight:400;color:#8b1a1a;letter-spacing:.03em;}\n"
    ".signature::before{content:'— ';color:#b0a090;font-style:normal;}\n"
)

# HTML側に挿入するブロック
HTML_SIGNATURE = '<div class="signature fade">e. Tamaki</div>'

# ---------------------------------------------------------------------------
# 検出パターン
# ---------------------------------------------------------------------------

# CSSの .note-box strong{...} 行 (柔軟にマッチ)
CSS_PATTERN = re.compile(
    r'(\.note-box\s+strong\s*\{[^}]*\})',
    re.MULTILINE
)

# HTMLの </div> ... <div class="tags fade"> の境界を探す
# note-box の閉じタグと tags の開始タグの間に署名を入れる
# 柔軟にマッチするため、class属性の順序や空白の揺れも吸収する
HTML_BOUNDARY_PATTERN = re.compile(
    r'(</div>\s*\n)(\s*)(<div\s+class\s*=\s*["\'](?:[^"\']*\s)?tags(?:\s[^"\']*)?["\']\s*(?:fade\s*)?["\']?\s*>)',
    re.MULTILINE
)

# もっとシンプルなパターン: <div class="tags fade"> または <div class="fade tags">
# note-box の直後のtagsを探す
TAGS_OPEN_PATTERN = re.compile(
    r'<div\s+class\s*=\s*["\']([^"\']*\btags\b[^"\']*)["\']\s*>'
)

# 既に適用済みか確認
SIGNATURE_APPLIED_PATTERN = re.compile(
    r'<div\s+class\s*=\s*["\'][^"\']*\bsignature\b[^"\']*["\']\s*>\s*e\.\s*Tamaki\s*</div>'
)

CSS_APPLIED_PATTERN = re.compile(r'\.signature\s*\{[^}]*font-family')


# ---------------------------------------------------------------------------
# 処理ロジック
# ---------------------------------------------------------------------------

class Result:
    OK = "✓"           # 適用可能 / 適用済み
    SKIP = "-"         # 既に適用済み
    WARN = "⚠"         # 片方しか見つからない等
    FAIL = "✗"         # note-box自体がない等

    def __init__(self, path, status, message, new_content=None):
        self.path = path
        self.status = status
        self.message = message
        self.new_content = new_content


def process_file(path: Path) -> Result:
    """1つのindex.htmlを処理する。new_content は書き換え後の内容 (適用しない場合も生成する)。"""
    try:
        original = path.read_text(encoding='utf-8')
    except Exception as e:
        return Result(path, Result.FAIL, f"読み込みエラー: {e}")

    # 既に適用済みか確認
    css_already = bool(CSS_APPLIED_PATTERN.search(original))
    html_already = bool(SIGNATURE_APPLIED_PATTERN.search(original))

    if css_already and html_already:
        return Result(path, Result.SKIP, "既に適用済み")

    # note-box が存在するか
    has_note_box = 'note-box' in original
    if not has_note_box:
        return Result(path, Result.FAIL, "note-box が見つからない")

    content = original

    # --- CSS追加 ---
    if not css_already:
        css_match = CSS_PATTERN.search(content)
        if not css_match:
            return Result(path, Result.WARN, ".note-box strong{...} のパターンが見つからない")

        # マッチした箇所の直後に改行+CSS_ADDITIONを挿入
        insert_pos = css_match.end()
        # マッチの直後が改行かどうか見て、綺麗につなげる
        if insert_pos < len(content) and content[insert_pos] == '\n':
            new_css = '\n' + CSS_ADDITION.rstrip('\n')
            content = content[:insert_pos] + new_css + content[insert_pos:]
        else:
            new_css = '\n' + CSS_ADDITION
            content = content[:insert_pos] + new_css + content[insert_pos:]

    # --- HTML挿入 ---
    if not html_already:
        # <div class="tags ..."> を探して、その直前に署名を入れる
        # ただしnote-boxの直後のtagsを対象にする
        # 戦略: note-box の </div> から tags の <div> までの範囲を探す
        note_box_open = re.search(r'<div\s+class\s*=\s*["\'][^"\']*\bnote-box\b[^"\']*["\']\s*>', content)
        if not note_box_open:
            return Result(path, Result.WARN, "note-box のdivタグが見つからない")

        # note-box の開始位置から、対応する </div> を探す
        # note-box 内にネストした div があるかもしれないので、数を数える
        start = note_box_open.end()
        depth = 1
        pos = start
        nested_div = re.compile(r'<div\b|</div>')
        while depth > 0 and pos < len(content):
            m = nested_div.search(content, pos)
            if not m:
                return Result(path, Result.WARN, "note-box の閉じタグが見つからない")
            if m.group() == '</div>':
                depth -= 1
                pos = m.end()
            else:
                depth += 1
                pos = m.end()

        note_box_end = pos  # これが note-box の </div> の直後の位置

        # note-box の閉じタグの後から、次の <div class="...tags..."> を探す
        remainder = content[note_box_end:]
        tags_match = TAGS_OPEN_PATTERN.search(remainder)
        if not tags_match:
            return Result(path, Result.WARN, "note-box 直後に tags ブロックが見つからない")

        # note-box と tags の間の文字列を確認 (空白・改行・HTMLコメントのみ許容)
        between = remainder[:tags_match.start()]
        # HTMLコメントを除去してから空白チェック
        between_stripped = re.sub(r'<!--.*?-->', '', between, flags=re.DOTALL)
        if between_stripped.strip():
            return Result(
                path,
                Result.WARN,
                f"note-box と tags の間に想定外の要素がある: {repr(between_stripped.strip()[:50])}"
            )

        # tags の直前 (note-box の直後 + between) に署名を挿入
        abs_tags_start = note_box_end + tags_match.start()

        # インデントを推測: tags が持っているインデントと同じにする
        # between の末尾から行頭までの空白を取る
        # (例: "\n\n" の後に "<div class=...") → インデントなし
        # (例: "\n  " の後に "<div class=...") → 2スペース
        indent_match = re.search(r'\n([ \t]*)$', between)
        indent = indent_match.group(1) if indent_match else ''

        signature_block = f'{indent}{HTML_SIGNATURE}\n\n{indent}'

        # between の末尾の空白部分を調整する
        # シンプルに: tags の直前に signature + 改行 + インデント を入れる
        new_content = (
            content[:abs_tags_start]
            + HTML_SIGNATURE + '\n\n' + indent
            + content[abs_tags_start:]
        )
        content = new_content

    return Result(path, Result.OK, "適用可能", new_content=content)


def find_article_files(root: Path):
    """リポジトリ直下の各サブフォルダ/index.html を探す。ルート直下のindex.htmlも含める。"""
    results = []
    # ルート直下 index.html (トップページ) は除外する
    # ただしサブフォルダの index.html は対象
    for item in sorted(root.iterdir()):
        if not item.is_dir():
            continue
        # 除外するフォルダ
        if item.name.startswith('.'):
            continue
        if item.name in ('node_modules', 'timeline', 'topic_map'):
            # timeline と topic_map は記事ではないので除外
            continue
        candidate = item / 'index.html'
        if candidate.is_file():
            results.append(candidate)
    return results


def show_diff(original: str, modified: str, path: Path):
    """unified diff を表示"""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f'a/{path}',
        tofile=f'b/{path}',
        n=3,
    )
    sys.stdout.writelines(diff)


def main():
    parser = argparse.ArgumentParser(
        description='Qualia Journal の全記事に署名ブロックを一括適用する'
    )
    parser.add_argument('root', type=str, help='リポジトリのルートディレクトリ')
    parser.add_argument('--apply', action='store_true',
                        help='実際にファイルを書き換える (デフォルトはdry-run)')
    parser.add_argument('--diff', action='store_true',
                        help='差分を表示する')
    parser.add_argument('--only', type=str, default=None,
                        help='指定したフォルダ名だけを処理する (例: --only libet_free_will)')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"エラー: {root} はディレクトリではない", file=sys.stderr)
        sys.exit(1)

    files = find_article_files(root)

    if args.only:
        files = [f for f in files if f.parent.name == args.only]
        if not files:
            print(f"エラー: {args.only} に一致する記事が見つからない", file=sys.stderr)
            sys.exit(1)

    print(f"対象ファイル数: {len(files)}")
    print(f"モード: {'APPLY (書き換えあり)' if args.apply else 'DRY-RUN (書き換えなし)'}")
    print("=" * 70)

    counts = {Result.OK: 0, Result.SKIP: 0, Result.WARN: 0, Result.FAIL: 0}
    warn_list = []
    fail_list = []

    for path in files:
        result = process_file(path)
        counts[result.status] += 1
        rel = path.relative_to(root)
        print(f"  {result.status}  {rel}  —  {result.message}")

        if result.status == Result.WARN:
            warn_list.append(rel)
        elif result.status == Result.FAIL:
            fail_list.append(rel)

        if args.diff and result.new_content is not None:
            original = path.read_text(encoding='utf-8')
            show_diff(original, result.new_content, rel)

        if args.apply and result.status == Result.OK and result.new_content is not None:
            path.write_text(result.new_content, encoding='utf-8')

    print("=" * 70)
    print(f"集計:")
    print(f"  ✓ 適用可能/適用済み: {counts[Result.OK]}")
    print(f"  - スキップ (適用済み): {counts[Result.SKIP]}")
    print(f"  ⚠ 要確認: {counts[Result.WARN]}")
    print(f"  ✗ 失敗: {counts[Result.FAIL]}")

    if warn_list:
        print(f"\n⚠ 要確認のファイル:")
        for p in warn_list:
            print(f"    {p}")

    if fail_list:
        print(f"\n✗ 失敗したファイル:")
        for p in fail_list:
            print(f"    {p}")

    if not args.apply:
        print(f"\n※ これは dry-run。実際に書き換えるには --apply を付けて実行する")
        print(f"※ 書き換え後は git diff で確認し、問題あれば git checkout -- . で戻せる")


if __name__ == '__main__':
    main()
