import os
import sys

def create_desktop_shortcut():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    shortcut_path = os.path.join(desktop, "Makalah Kilat.lnk")
    project_dir = os.path.dirname(os.path.abspath(__file__))
    target_bat = os.path.join(project_dir, "Buka_Makalah_Kilat.bat")

    vbs_content = f"""Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_bat}"
oLink.WorkingDirectory = "{project_dir}"
oLink.Description = "Asisten Tugas Citra - Makalah Kilat"
oLink.Save
"""
    vbs_path = os.path.join(project_dir, "temp_shortcut.vbs")
    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        os.system(f'cscript //nologo "{vbs_path}"')
        print(f"Ikon pintasan berhasil dibuat di Desktop: {shortcut_path}")
    finally:
        if os.path.exists(vbs_path):
            os.remove(vbs_path)

if __name__ == "__main__":
    create_desktop_shortcut()
