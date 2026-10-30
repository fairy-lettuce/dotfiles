# packages.kdl の手書きコメント退避

`pkgnote` は packages.kdl を書き戻す際、正準シリアライザで全体を再生成するため、
ファイル先頭の生成ヘッダ以外のコメントは失われる(`src/pkgnote/kdl.py` 冒頭の
トレードオフ記述を参照)。次に `pkgnote fetch` / `categorize` が書き込むと消える
コメントを、ここに退避しておく。

| 対象パッケージ | コメント |
| --- | --- |
| `tool/gui/audio-visual` の `com.obsproject.Studio` (flatpak) | `// Duplicate!`(pacman の `obs-studio` と重複) |
| `tool/gui/filer` の `ffmpegthumbnailer` | `// dependency for GUI filers` |
| `tool/gui/remote-control` の `apollo` (foreign) | `// sunshine fork` |
| `tool/gui/remote-control` の `artemis-qt-git` (foreign) | `// moonlight fork, but currently unoperational possibly due to a bug` |
| `system/font/other` カテゴリ | `// emoji, nerd fonts, powerline glyphs` |

TODO: pkgnote 側でコメントの round-trip 保持を実装したら、上記を KDL に書き戻してこのファイルを畳む。
