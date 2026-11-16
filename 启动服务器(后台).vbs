' 后台静默启动 ELN 服务器（无窗口；停止：任务管理器结束 pythonw.exe）
' 登录地址：http://127.0.0.1:8765/login
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = base
sh.Run """pythonw.exe"" """ & base & "\webapp.py"" --auth --host 0.0.0.0 --no-browser", 0, False
