"""
AI小说写作软件 - 启动器
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from gui_app import main
    main()