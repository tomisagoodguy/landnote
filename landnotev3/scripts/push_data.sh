#!/usr/bin/env bash
# CI 自動 commit 後推回 main。另一次 run 可能剛推過同一批產出檔，衝突一律以本次產出為準：
#   - 內容衝突：rebase 加 -X theirs（rebase 中 theirs＝正在重放的本次 commit）
#   - 修改／刪除等 -X 解不了的衝突：逐檔取本次 commit 的版本，本次沒有該檔就刪除
# push 被搶先就整段重來，最多 5 次。用法：bash landnotev3/scripts/push_data.sh
set -u

resolve_with_ours_run() {
  # 處理 rebase 停下來的所有未合併檔案，再繼續 rebase；最多處理 20 個 commit 避免無窮迴圈
  local n=0
  while git rev-parse -q --verify REBASE_HEAD >/dev/null; do
    n=$((n + 1))
    if [ "$n" -gt 20 ]; then return 1; fi
    git diff --name-only --diff-filter=U -z | while IFS= read -r -d '' f; do
      if git cat-file -e ":3:$f" 2>/dev/null; then
        git checkout --theirs -- "$f" && git add -- "$f"
      else
        git rm -q -- "$f"
      fi
    done
    if [ -n "$(git diff --name-only --diff-filter=U)" ]; then return 1; fi
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true
  done
}

sync_and_push() {
  if ! git pull --rebase -X theirs origin main; then
    git rev-parse -q --verify REBASE_HEAD >/dev/null || return 1  # 不是衝突（例如網路錯誤）
    echo "rebase 有 -X theirs 解不了的衝突，逐檔取本次產出"
    resolve_with_ours_run || return 1
  fi
  git push
}

for i in 1 2 3 4 5; do
  if sync_and_push; then exit 0; fi
  git rebase --abort 2>/dev/null || true
  echo "push 失敗（第 $i 次），稍後重試"
  sleep $((i * 10))
done
echo "::error::重試 5 次仍無法推送資料變更"
exit 1
