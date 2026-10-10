#!/bin/zsh
cd -- "${0:A:h:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print '缺少 .venv。请按 README 创建 Python 3.11+ 虚拟环境。'
  exit 1
fi
exec .venv/bin/python -m app.main "$@"
