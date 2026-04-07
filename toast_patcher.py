#!/usr/bin/env python3
"""
Qualia Journal — トーストツールチップ一括パッチャー

既存記事HTMLのツールチップを、画面下トースト方式に置き換える。
横スクロール対策CSSも同時に適用する。

使い方:
    # ★ Qualia Journal サイト全体に適用するとき（推奨）
    python3 toast_patcher.py /path/to/site --articles-mode --dry-run
    python3 toast_patcher.py /path/to/site --articles-mode

    # ドライラン（何も書き換えず、各ファイルの状態を報告）
    python3 toast_patcher.py /path/to/articles --dry-run

    # 実適用（バックアップ .bak を作成してから書き換え）
    python3 toast_patcher.py /path/to/articles

    # 単一ファイル
    python3 toast_patcher.py /path/to/article.html

    # 除外パターン指定
    python3 toast_patcher.py /path/to/articles --exclude "index*" "timeline*" "topic_map*"

    # バックアップを作らない
    python3 toast_patcher.py /path/to/articles --no-backup

--articles-mode について:
    Qualia Journal のサイト構造を前提にしたモード。

        site/
        ├── index.html              ← トップ。除外
        ├── articles.js など         ← ルート直下のhtml以外も無視
        ├── monty_hall/
        │   └── index.html          ← パッチ対象
        ├── color/
        │   └── index.html          ← パッチ対象
        ├── timeline/  topic_map/  about/  contact/  assets/
        │   └── ...                 ← --exclude-dirs で指定したものは除外

    デフォルトの除外サブディレクトリ: timeline, topic_map, about, contact, assets
    変更したい場合は --exclude-dirs で上書き

特徴:
- 安全: パッチが完全に成功した場合のみファイルを書き換える
- 冪等: すでにパッチ済みのファイルはスキップ
- 防御的: toggleTip関数のバリエーション(1行・複数行・コメント有無)に対応
- 報告: どのファイルがどう処理されたかを明示

Python 3.8+ 標準ライブラリのみで動作（外部依存なし）
"""
import argparse
import re
import shutil
import sys
import fnmatch
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple

# ============================================================================
# パッチ内容
# ============================================================================

CSS_PATCH = (
    "html,body{overflow-x:hidden;max-width:100%;}"
    "img,canvas,svg,video{max-width:100%;height:auto;}"
    ".sim-canvas-wrap{max-width:100%;}"
    ".sim-canvas-wrap canvas{max-width:100%;height:auto;}"
    ".t-line{min-width:0;}"
    ".t-input,.t-output,.t-prompt{word-break:break-word;overflow-wrap:anywhere;min-width:0;}"
    ".body-text,.ref-desc,.ref-title,.ref-author,.quote-en,.quote-ja,.tl-desc,.culture-desc,.sidebar-text,.img-ph-desc,.img-ph-prompt-txt{overflow-wrap:anywhere;}"
    "@media(max-width:720px){"
    ".meta-bar{padding:14px 20px;flex-wrap:wrap;gap:14px;}"
    ".meta-dates{margin-left:0;width:100%;}"
    "}"
    ".tip-box{display:none!important;}"
    ".tip{border-bottom:1px dotted #8b1a1a;color:inherit;cursor:pointer;display:inline;transition:background .15s;}"
    ".tip.open{background:#fdf3d8;}"
    ".tip-toast{position:fixed;left:12px;right:12px;bottom:-300px;background:#1a1208;color:#e8e4de;padding:18px 20px 20px;font-family:'Source Sans 3',sans-serif;font-size:13px;font-weight:300;line-height:1.7;z-index:500;box-shadow:0 -8px 32px rgba(0,0,0,.3);transition:bottom .3s cubic-bezier(.22,1,.36,1);max-width:560px;margin:0 auto;}"
    ".tip-toast.show{bottom:16px;}"
    ".tip-toast-title{display:block;font-family:'Source Sans 3',sans-serif;font-size:11px;font-weight:600;letter-spacing:.12em;color:#e8c56a;text-transform:uppercase;margin-bottom:8px;padding-right:28px;}"
    ".tip-toast-body{font-size:13px;line-height:1.75;color:#e8e4de;}"
    ".tip-toast-close{position:absolute;top:14px;right:14px;width:26px;height:26px;background:none;border:none;color:#7a6a55;font-size:22px;line-height:1;cursor:pointer;padding:0;}"
    ".tip-toast-close:hover{color:#e8c56a;}"
    ".tip-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0);z-index:499;pointer-events:none;transition:background .3s;}"
    ".tip-backdrop.show{background:rgba(0,0,0,.18);pointer-events:auto;}"
)

NEW_JS = r"""// ツールチップ（トースト方式）
function _tipExtract(el){const box=el.querySelector('.tip-box');if(!box)return{title:el.textContent.trim(),body:''};const strong=box.querySelector('strong');let title='';let body='';if(strong){title=strong.textContent.trim();const clone=box.cloneNode(true);const s=clone.querySelector('strong');if(s)s.remove();const br=clone.querySelector('br');if(br)br.remove();body=clone.textContent.trim();}else{title=el.textContent.trim();body=box.textContent.trim();}return{title,body};}
function _tipCloseToast(){const t=document.getElementById('tipToast');const b=document.getElementById('tipBackdrop');if(t)t.classList.remove('show');if(b)b.classList.remove('show');document.querySelectorAll('.tip.open').forEach(x=>x.classList.remove('open'));}
function toggleTip(el){const wasOpen=el.classList.contains('open');document.querySelectorAll('.tip.open').forEach(t=>t.classList.remove('open'));if(wasOpen){_tipCloseToast();return;}el.classList.add('open');const{title,body}=_tipExtract(el);const tt=document.getElementById('tipToastTitle');const tb=document.getElementById('tipToastBody');const toast=document.getElementById('tipToast');const backdrop=document.getElementById('tipBackdrop');if(!toast)return;tt.textContent=title;tb.textContent=body;toast.classList.add('show');backdrop.classList.add('show');}
document.addEventListener('click',e=>{if(!e.target.closest('.tip')&&!e.target.closest('.tip-toast'))_tipCloseToast();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')_tipCloseToast();});"""

TOAST_HTML = (
    '<div class="tip-backdrop" id="tipBackdrop"></div>'
    '<div class="tip-toast" id="tipToast">'
    '<button class="tip-toast-close" id="tipToastClose" aria-label="閉じる" onclick="_tipCloseToast()">×</button>'
    '<span class="tip-toast-title" id="tipToastTitle"></span>'
    '<div class="tip-toast-body" id="tipToastBody"></div>'
    '</div>'
)

# ============================================================================
# パッチロジック
# ============================================================================

TOGGLETIP_FUNC_START = re.compile(r'function\s+toggleTip\s*\([^)]*\)\s*\{')

DOC_CLICK_HANDLER = re.compile(
    r"document\.addEventListener\s*\(\s*['\"]click['\"]\s*,\s*"
    r"(?:function\s*\([^)]*\)|[^,)]*=>)\s*\{",
    re.DOTALL
)


@dataclass
class PatchResult:
    path: Path
    status: str
    reason: str = ''
    tip_count: int = 0


def find_balanced_brace_end(text: str, start: int) -> int:
    """text[start] が '{' のとき、対応する '}' のインデックスを返す。文字列・コメント考慮。"""
    depth = 0
    in_string = None
    in_line_comment = False
    in_block_comment = False
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i+1] if i+1 < n else ''
        if in_line_comment:
            if c == '\n':
                in_line_comment = False
        elif in_block_comment:
            if c == '*' and nxt == '/':
                in_block_comment = False
                i += 1
        elif in_string:
            if c == '\\':
                i += 1
            elif c == in_string:
                in_string = None
        else:
            if c == '/' and nxt == '/':
                in_line_comment = True
                i += 1
            elif c == '/' and nxt == '*':
                in_block_comment = True
                i += 1
            elif c in ('"', "'", '`'):
                in_string = c
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def remove_old_toggle_tip(src: str) -> Tuple[str, bool]:
    """旧 toggleTip 関数とそれに続く tip 関連の document click handler を削除して新JSに置換。"""
    m = TOGGLETIP_FUNC_START.search(src)
    if not m:
        return src, False

    func_brace_start = m.end() - 1
    func_brace_end = find_balanced_brace_end(src, func_brace_start)
    if func_brace_end == -1:
        return src, False

    func_start = m.start()
    func_end = func_brace_end + 1

    after = func_end
    while after < len(src) and src[after] in ' \t':
        after += 1
    if after < len(src) and src[after] == '\n':
        after += 1

    tail_search_limit = min(after + 500, len(src))
    tail = src[after:tail_search_limit]
    handler_match = DOC_CLICK_HANDLER.search(tail)
    handler_end_in_src = after
    if handler_match:
        handler_brace_start = after + handler_match.end() - 1
        handler_body_end = find_balanced_brace_end(src, handler_brace_start)
        if handler_body_end != -1:
            handler_body = src[handler_brace_start:handler_body_end+1]
            if '.tip' in handler_body or 'tip.open' in handler_body:
                pos = handler_body_end + 1
                while pos < len(src) and src[pos] in ' \t':
                    pos += 1
                if pos < len(src) and src[pos] == ')':
                    pos += 1
                if pos < len(src) and src[pos] == ';':
                    pos += 1
                if pos < len(src) and src[pos] == '\n':
                    pos += 1
                handler_end_in_src = pos

    line_start = func_start
    while line_start > 0 and src[line_start-1] != '\n':
        line_start -= 1
    if line_start < func_start:
        prev_line = src[line_start:func_start].strip()
        if prev_line.startswith('//') and ('ツールチップ' in prev_line or 'tip' in prev_line.lower() or 'tooltip' in prev_line.lower()):
            func_start = line_start

    new_src = src[:func_start] + NEW_JS + '\n' + src[handler_end_in_src:]
    return new_src, True


def patch_html(content: str) -> Tuple[Optional[str], str, int]:
    tip_count = len(re.findall(r'class\s*=\s*["\'][^"\']*\btip\b[^"\']*["\']', content))

    if 'tip-toast' in content and '_tipCloseToast' in content:
        return None, 'skipped_already', tip_count

    src = content

    style_idx = src.find('</style>')
    if style_idx == -1:
        return None, 'failed', tip_count
    src = src[:style_idx] + CSS_PATCH + src[style_idx:]

    if tip_count > 0:
        src, ok = remove_old_toggle_tip(src)
        if not ok:
            return None, 'failed', tip_count

    if '</body>' not in src:
        return None, 'failed', tip_count
    src = src.replace('</body>', TOAST_HTML + '</body>', 1)

    return src, 'patched', tip_count


def process_file(path: Path, backup: bool, dry_run: bool) -> PatchResult:
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        return PatchResult(path, 'failed', f'read error: {e}')

    new_content, status, tip_count = patch_html(content)

    if status == 'failed':
        return PatchResult(path, 'failed', 'patch logic failed (toggleTip not found or </style>/</body> missing)', tip_count)

    if status == 'skipped_already':
        return PatchResult(path, 'skipped_already', 'already patched', tip_count)

    if dry_run:
        return PatchResult(path, status, '(dry-run)', tip_count)

    if backup:
        backup_path = path.with_suffix(path.suffix + '.bak')
        try:
            shutil.copy2(path, backup_path)
        except Exception as e:
            return PatchResult(path, 'failed', f'backup error: {e}', tip_count)

    try:
        path.write_text(new_content, encoding='utf-8')
    except Exception as e:
        return PatchResult(path, 'failed', f'write error: {e}', tip_count)

    return PatchResult(path, status, '', tip_count)


def collect_targets(target: Path, exclude_patterns: List[str],
                    articles_mode: bool = False,
                    exclude_dirs: Optional[List[str]] = None) -> List[Path]:
    """対象ファイル一覧を収集する。

    通常モード:
        target がファイルならそのファイル。
        target がディレクトリなら直下の *.html を取り、なければ再帰的に *.html を取る。
        exclude_patterns (ファイル名glob) にマッチするものは除外。

    articles_mode:
        Qualia Journalのサイト構造を前提:
            site/
            ├── index.html              ← トップ。除外
            ├── 各種.html / .js / .css  ← 除外
            ├── article_slug_a/
            │   └── index.html          ← 対象
            ├── article_slug_b/
            │   └── index.html          ← 対象
            ├── timeline/  topic_map/  about/  contact/  assets/
            │   └── ...                 ← 除外（exclude_dirsで指定）

        ルート直下のhtmlは無条件で除外。
        exclude_dirs に該当するサブディレクトリは丸ごと除外。
        それ以外のサブディレクトリ内の *.html は対象。
    """
    if target.is_file():
        return [target]

    if articles_mode:
        if exclude_dirs is None:
            exclude_dirs = []
        exclude_dirs_set = set(exclude_dirs)
        filtered = []
        for sub in sorted(target.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name in exclude_dirs_set:
                continue
            if sub.name.startswith('.'):
                continue
            for f in sorted(sub.rglob('*.html')):
                if f.suffix == '.bak' or f.name.endswith('.bak'):
                    continue
                # 追加のファイル名除外もここで適用
                skip = False
                for pat in exclude_patterns:
                    if fnmatch.fnmatch(f.name, pat):
                        skip = True
                        break
                if not skip:
                    filtered.append(f)
        return filtered

    # 通常モード
    files = sorted(target.glob('*.html'))
    if not files:
        files = sorted(target.rglob('*.html'))

    filtered = []
    for f in files:
        if f.suffix == '.bak' or f.name.endswith('.bak'):
            continue
        skip = False
        for pat in exclude_patterns:
            if fnmatch.fnmatch(f.name, pat):
                skip = True
                break
        if not skip:
            filtered.append(f)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description='Qualia Journal トーストツールチップ一括パッチャー',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('target', help='記事HTMLファイル または ディレクトリ')
    parser.add_argument('--dry-run', action='store_true', help='実際には書き換えず、レポートだけ出す')
    parser.add_argument('--no-backup', action='store_true', help='.bakファイルを作らない')
    parser.add_argument('--articles-mode', action='store_true',
                        help='Qualia Journal サイト構造モード: ルート直下のhtmlを除外し、サブディレクトリの記事index.htmlのみを対象にする')
    parser.add_argument('--exclude-dirs', nargs='*',
                        default=['timeline', 'topic_map', 'about', 'contact', 'assets'],
                        help='--articles-mode のときに除外するサブディレクトリ名')
    parser.add_argument('--exclude', nargs='*',
                        default=['index*.html', 'timeline*.html', 'topic_map*.html', 'template*.html'],
                        help='除外するファイル名パターン (--articles-modeのときは無効化される)')
    args = parser.parse_args()

    # articles-mode のときはファイル名除外を空にする（サブディレクトリの index.html を取りたいので）
    if args.articles_mode:
        args.exclude = []

    target = Path(args.target).resolve()
    if not target.exists():
        print(f'ERROR: {target} not found', file=sys.stderr)
        sys.exit(1)

    files = collect_targets(target, args.exclude,
                            articles_mode=args.articles_mode,
                            exclude_dirs=args.exclude_dirs)
    if not files:
        print(f'対象ファイルが見つかりません: {target}')
        sys.exit(0)

    print(f'対象: {len(files)} files')
    if args.articles_mode:
        print(f'モード: articles-mode (除外サブディレクトリ: {args.exclude_dirs})')
    else:
        print(f'除外パターン: {args.exclude}')
    if args.dry_run:
        print('モード: ドライラン (書き換えなし)')
    else:
        print(f'モード: 実適用 (バックアップ: {"なし" if args.no_backup else ".bak ファイルを作成"})')
    print('-' * 70)

    results = []
    for f in files:
        result = process_file(f, backup=not args.no_backup, dry_run=args.dry_run)
        results.append(result)
        marker = {
            'patched': '✓',
            'skipped_already': '·',
            'failed': '✗',
        }.get(result.status, '?')
        # 表示名: articles-mode のときは parent/name 形式、それ以外は name のみ
        if args.articles_mode and result.path.parent != target:
            display_name = f'{result.path.parent.name}/{result.path.name}'
        else:
            display_name = result.path.name
        suffix = f' — {result.reason}' if result.reason else ''
        print(f'  {marker} {display_name}  [{result.status}] tips={result.tip_count}{suffix}')

    print('-' * 70)
    summary = {}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    print('サマリー:')
    for k, v in sorted(summary.items()):
        print(f'  {k}: {v}')

    failed = [r for r in results if r.status == 'failed']
    if failed:
        print()
        print('失敗したファイル:')
        for r in failed:
            print(f'  - {r.path}: {r.reason}')
        print()
        print('上記のファイルは個別に確認してください。')
        print('（パッチは適用されていません。バックアップも作成されていません。）')
        sys.exit(2)

    print()
    print('完了。')
    if not args.dry_run and not args.no_backup:
        print('元のファイルは .bak として保存されています。問題なければ .bak は削除してください。')


if __name__ == '__main__':
    main()
