Option Explicit

Dim pythonPath

'***********************************************************
'�������e��Python 2.7�̃p�X�ɏ��������Ă�������
pythonPath = ""
'pythonPath = "C:\Python27\python.exe"
'***********************************************************

If Wscript.Arguments.Count = 0 Then
  MsgBox "�ϊ�����f�B���N�g�����h���b�O���h���b�v���Ă��������B", 48, "azw2zip"
  Wscript.Quit
End If

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")

Dim vbsPath
vbsPath = fso.getParentFolderName(WScript.ScriptFullName)

Dim WshShell
Set WshShell = WScript.CreateObject("WScript.Shell")

If pythonPath = "" Then
  MsgBox "Python�̃p�X���ݒ肳��Ă��܂���B" & vbCrLf & "azw2zip.vbs ��ҏW���� python.exe �̃p�X��ݒ肵�Ă��������B", 48, "azw2zip"
  EditVBS(vbsPath & "\azw2zip.vbs")
  Wscript.Quit
End If

If fso.FileExists(pythonPath) = False Then
  MsgBox pythonPath + " ��������܂���B" & vbCrLf & "azw2zip.vbs ��ҏW���� python.exe �̃p�X��ݒ肵�Ă��������B", 48, "azw2zip"
  EditVBS(vbsPath & "\azw2zip.vbs")
  Wscript.Quit
End If

Dim pythonCmd

pythonCmd = pythonPath + " """ & vbsPath & "\azw2zip.py"" """ & Wscript.Arguments.Item(0) & """ """ & vbsPath & """"
'zip�łȂ�EPUB�ŏo�͂���Ȃ牺�̍s�̃R�����g������
'pythonCmd = pythonPath + " """ & vbsPath & "\azw2zip.py"" -e """ & Wscript.Arguments.Item(0) & """ """ & vbsPath & """"

WshShell.Run(pythonCmd)

Set WshShell = Nothing
Set fso = Nothing

'�������ł��̃t�@�C�����J��
Sub EditVBS(FilePath)
  WshShell.Run "%windir%\system32\notepad.exe """ & FilePath & """", 1, False
End Sub
