@echo off
rem 指定 Python 解释器（可选）。默认用 PATH 里的 python / pythonw。
rem 需要别的环境时：set ELN_HOME=C:\路径\到\python 目录
if defined ELN_HOME set "PATH=%ELN_HOME%;%ELN_HOME%\Scripts;%PATH%"
if defined ELN_PYTHON (
  set "ELN_PY=%ELN_PYTHON%"
) else (
  set "ELN_PY=python"
)
if defined ELN_PYTHONW (
  set "ELN_PYW=%ELN_PYTHONW%"
) else (
  set "ELN_PYW=pythonw"
)
