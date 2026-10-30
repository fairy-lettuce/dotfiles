#!/bin/sh
# pkgnote-fetch.hook から root で呼ばれるヘルパー。
# 呼び出しユーザーのログイン環境に降りて `pkgnote fetch` を実行する。
# PostTransaction フックの失敗はトランザクションに影響しないが、念のため握りつぶす。
[ -n "$SUDO_USER" ] || exit 0
runuser -l "$SUDO_USER" -c 'pkgnote fetch' || true
