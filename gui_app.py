"""
AI小说写作软件 - 图形界面（流畅版）
支持单章、批量、自动写完整本
"""

import sys
import os
import json
import time
import traceback
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QLineEdit, QComboBox, QTabWidget,
    QSplitter, QListWidget, QMessageBox, QFileDialog, QProgressBar,
    QGroupBox, QFormLayout, QSpinBox, QCheckBox, QStatusBar, QAction,
    QToolBar, QDialog, QDialogButtonBox, QTextBrowser, QRadioButton,
    QButtonGroup, QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt5.QtGui import QFont

from ai_models import ModelFactory, ConfigManager
from novel_engine import NovelEngine


# ============ 工作线程 ============
class AIWorkerThread(QThread):
    """AI工作线程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")


# ============ 批量写作控制器 ============
class BatchWriterController(QObject):
    """批量写作控制器 - 在后台线程运行"""
    chapter_done = pyqtSignal(int, str, str)
    progress = pyqtSignal(int, int, str)
    all_done = pyqtSignal()
    write_error = pyqtSignal(int, str)
    auto_saved = pyqtSignal(str)
    
    def __init__(self, engine, chapter_range, settings):
        super().__init__()
        self.engine = engine
        self.chapter_range = chapter_range
        self.settings = settings
        self._stopped = False
        self.previous_content = ""
    
    def stop(self):
        self._stopped = True
    
    def run(self):
        """后台执行批量写作"""
        start, end = self.chapter_range
        total = end - start + 1
        
        for i, chapter_num in enumerate(range(start, end + 1)):
            if self._stopped:
                self.progress.emit(i, total, "⏹ 用户停止")
                break
            
            try:
                # 获取大纲
                chapter_outline = self._get_chapter_outline(chapter_num)
                
                # 获取前情提要
                prev_summary = self._get_prev_summary()
                
                # 生成标题
                title = self._generate_title(chapter_num, chapter_outline)
                
                # 写作
                self.progress.emit(i, total, f"正在写第{chapter_num}章《{title}》...")
                
                content = self.engine.write_chapter(
                    chapter_num=chapter_num,
                    chapter_title=title,
                    chapter_outline=chapter_outline,
                    previous_summary=prev_summary,
                    extra_instructions=self.settings.get("extra", "")
                )
                
                # 检查返回值
                if content is None:
                    raise Exception("API返回为空")
                if isinstance(content, str) and content.startswith("[Error]"):
                    raise Exception(content)
                
                self.previous_content = content
                self.chapter_done.emit(chapter_num, title, content)
                
                # 每5章自动保存
                if chapter_num % 5 == 0:
                    self._auto_save()
                
                time.sleep(2)
                
            except Exception as e:
                self.write_error.emit(chapter_num, str(e))
                time.sleep(5)
        
        self.all_done.emit()
    
    def _get_chapter_outline(self, chapter_num):
        """获取本章大纲"""
        base_outline = self.settings.get("outline", "")
        char_info = self.settings.get("characters", "")
        
        parts = []
        if char_info:
            parts.append(f"【角色设定（必须遵守）】\n{char_info[:1000]}")
        if base_outline:
            parts.append(f"【大纲参考】\n{base_outline[:1500]}")
        parts.append(f"【本章任务】写第{chapter_num}章，角色名和设定必须一致")
        
        return "\n\n".join(parts)
    
    def _get_prev_summary(self):
        """获取前情提要"""
        user_prev = self.settings.get("prev_summary", "")
        
        if self.settings.get("auto_continue", True) and self.previous_content:
            if len(self.previous_content) > 500:
                return f"上一章内容概要：\n{self.previous_content[:500]}...\n\n请继续写下一章，保持剧情连贯。"
            else:
                return f"上一章内容：\n{self.previous_content}\n\n请继续写下一章。"
        
        return user_prev if user_prev else ""
    
    def _generate_title(self, chapter_num, outline):
        """自动生成标题"""
        if not self.settings.get("auto_title", True):
            return f"第{chapter_num}章"
        
        try:
            novel = self.engine.novel_data
            prompt = f"""为小说第{chapter_num}章生成标题（8-15字，吸引人）。
类型：{novel.get('type', '')}
风格：{novel.get('tone', '')}
大纲：{outline[:200] if outline else '无'}
只返回标题，不要引号。"""
            
            messages = [
                {"role": "system", "content": "你是章节命名师。"},
                {"role": "user", "content": prompt}
            ]
            title = self.engine.ai.chat(messages, temperature=0.9, max_tokens=50)
            return title.strip().strip('"\'《》').strip()
        except:
            return f"第{chapter_num}章"
    
    def _auto_save(self):
        """自动保存"""
        try:
            os.makedirs("novels", exist_ok=True)
            title = self.engine.novel_data.get("title", "未命名")
            path = os.path.join("novels", f"{title}_auto.json")
            self.engine.save_project(path)
            self.auto_saved.emit(path)
        except:
            pass


# ============ API配置对话框 ============
class ApiKeyDialog(QDialog):
    """API配置对话框"""
    
    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ 配置AI模型")
        self.setMinimumWidth(550)
        self.current_config = current_config or {}
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        title = QLabel("🔌 连接AI模型")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        layout.addWidget(title)
        
        form_group = QGroupBox("连接设置")
        form = QFormLayout()
        form.setSpacing(10)
        
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("例如: https://api.longcat.chat")
        self.base_url_input.setMinimumHeight(35)
        form.addRow("API地址:", self.base_url_input)
        
        self.model_name_input = QLineEdit()
        self.model_name_input.setPlaceholderText("模型名称")
        self.model_name_input.setMinimumHeight(35)
        form.addRow("模型名称:", self.model_name_input)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("API密钥")
        self.api_key_input.setMinimumHeight(35)
        form.addRow("API密钥:", self.api_key_input)
        
        self.show_key_check = QCheckBox("显示密钥")
        self.show_key_check.toggled.connect(
            lambda checked: self.api_key_input.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        form.addRow("", self.show_key_check)
        
        form_group.setLayout(form)
        layout.addWidget(form_group)
        
        # 预设
        preset_group = QGroupBox("📌 快速填充")
        preset_layout = QVBoxLayout()
        
        presets = [
            ("LongCat", "https://api.longcat.chat", ""),
            ("DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
            ("硅基流动", "https://api.siliconflow.cn", "Qwen/Qwen2.5-7B-Instruct"),
            ("Ollama本地", "http://localhost:11434", "qwen2.5:7b"),
        ]
        
        for name, url, model in presets:
            btn = QPushButton(f"📋 {name}: {url}")
            btn.setStyleSheet("text-align: left; padding: 5px;")
            btn.clicked.connect(lambda checked, u=url, m=model: self.fill_preset(u, m))
            preset_layout.addWidget(btn)
        
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)
        
        # 测试连接
        self.test_btn = QPushButton("🔍 测试连接")
        self.test_btn.clicked.connect(self.test_connection)
        self.test_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; padding: 10px;
                         font-weight: bold; border-radius: 5px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        layout.addWidget(self.test_btn)
        
        self.test_result = QLabel("")
        self.test_result.setVisible(False)
        self.test_result.setStyleSheet("padding: 10px; border-radius: 5px;")
        layout.addWidget(self.test_result)
        
        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText("✅ 保存并连接")
        buttons.button(QDialogButtonBox.Cancel).setText("❌ 取消")
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def fill_preset(self, url, model):
        self.base_url_input.setText(url)
        if model:
            self.model_name_input.setText(model)
    
    def test_connection(self):
        api_key = self.api_key_input.text().strip()
        model_name = self.model_name_input.text().strip()
        base_url = self.base_url_input.text().strip()
        
        if not all([api_key, model_name, base_url]):
            QMessageBox.warning(self, "提示", "请填写完整信息")
            return
        
        self.test_btn.setEnabled(False)
        self.test_btn.setText("⏳ 测试中...")
        self.test_result.setVisible(True)
        self.test_result.setText("正在连接...")
        self.test_result.setStyleSheet("padding: 10px; background: #FFF3E0; border-radius: 5px;")
        
        def do_test():
            return ModelFactory.test_connection(api_key, model_name, base_url)
        
        self.test_thread = AIWorkerThread(do_test)
        self.test_thread.finished.connect(self.on_test_done)
        self.test_thread.error.connect(self.on_test_error)
        self.test_thread.start()
    
    def on_test_done(self, result):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("🔍 测试连接")
        success, msg = result
        if success:
            self.test_result.setText(msg)
            self.test_result.setStyleSheet("padding: 10px; background: #E8F5E9; color: #2E7D32; border-radius: 5px;")
        else:
            self.test_result.setText(f"❌ {msg}")
            self.test_result.setStyleSheet("padding: 10px; background: #FFEBEE; color: #C62828; border-radius: 5px;")
    
    def on_test_error(self, error_msg):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("🔍 测试连接")
        self.test_result.setText(f"❌ {error_msg}")
        self.test_result.setStyleSheet("padding: 10px; background: #FFEBEE; color: #C62828; border-radius: 5px;")
    
    def load_config(self):
        if self.current_config:
            self.base_url_input.setText(self.current_config.get("base_url", ""))
            self.model_name_input.setText(self.current_config.get("model_name", ""))
            self.api_key_input.setText(self.current_config.get("api_key", ""))
    
    def get_config(self):
        return {
            "base_url": self.base_url_input.text().strip(),
            "model_name": self.model_name_input.text().strip(),
            "api_key": self.api_key_input.text().strip()
        }


# ============ 主窗口 ============
class MainWindow(QMainWindow):
    """AI小说写作软件"""
    
    def __init__(self):
        super().__init__()
        self.engine = None
        self.ai_model = None
        self.config_manager = ConfigManager()
        self.worker = None
        self.batch_controller = None
        self.batch_thread = None
        self.is_writing = False
        
        self.init_ui()
        self.init_config()
    
    def init_ui(self):
        self.setWindowTitle("AI小说写作软件")
        self.setGeometry(100, 100, 1500, 900)
        
        self.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #ddd; border-radius: 8px;
                       margin-top: 15px; padding: 15px; background: white; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 8px; }
            QTextEdit, QTextBrowser { border: 1px solid #ddd; border-radius: 5px;
                                      padding: 10px; background: white; }
            QPushButton { padding: 8px 18px; border-radius: 5px; border: 1px solid #ccc; }
            QPushButton:hover { background-color: #e8e8e8; }
            QComboBox, QLineEdit, QSpinBox { padding: 8px; border: 1px solid #ddd;
                                             border-radius: 4px; background: white; }
            QTabWidget::pane { border: 1px solid #ddd; border-radius: 5px; background: white; }
            QTabBar::tab { padding: 10px 20px; }
            QTabBar::tab:selected { border-bottom: 3px solid #2196F3; }
        """)
        
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("👋 欢迎！请先配置AI模型")
        
        # 工具栏
        toolbar = self.addToolBar("工具栏")
        toolbar.setMovable(False)
        
        config_action = QAction("⚙ 配置AI", self)
        config_action.triggered.connect(self.show_api_dialog)
        toolbar.addAction(config_action)
        toolbar.addSeparator()
        
        save_action = QAction("💾 保存", self)
        save_action.triggered.connect(self.save_project)
        toolbar.addAction(save_action)
        
        load_action = QAction("📂 打开", self)
        load_action.triggered.connect(self.load_project)
        toolbar.addAction(load_action)
        
        export_action = QAction("📤 导出TXT", self)
        export_action.triggered.connect(self.export_novel)
        toolbar.addAction(export_action)
        toolbar.addSeparator()
        
        self.model_label = QLabel(" 未连接 ")
        self.model_label.setStyleSheet("color: red; font-weight: bold;")
        toolbar.addWidget(self.model_label)
        
        # 中央标签页
        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)
        
        self.create_project_tab()
        self.create_outline_tab()
        self.create_characters_tab()
        self.create_writing_tab()
        self.create_preview_tab()
    
    # ============ 标签页创建 ============
    
    def create_project_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        group = QGroupBox("📋 基本信息")
        form = QFormLayout()
        form.setSpacing(8)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("输入小说名...")
        self.title_input.setMinimumHeight(35)
        form.addRow("书名:", self.title_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["玄幻", "都市", "科幻", "历史", "悬疑", "言情", "武侠", "游戏", "末日", "其他"])
        self.type_combo.setMinimumHeight(35)
        form.addRow("类型:", self.type_combo)
        
        self.tone_combo = QComboBox()
        self.tone_combo.addItems(["轻松搞笑", "严肃正剧", "虐心感人", "热血燃", "温馨治愈", "暗黑压抑"])
        self.tone_combo.setMinimumHeight(35)
        form.addRow("风格:", self.tone_combo)
        
        self.perspective_combo = QComboBox()
        self.perspective_combo.addItems(["第三人称", "第一人称"])
        self.perspective_combo.setMinimumHeight(35)
        form.addRow("视角:", self.perspective_combo)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        desc_group = QGroupBox("📖 小说描述")
        desc_layout = QVBoxLayout()
        self.desc_text = QTextEdit()
        self.desc_text.setPlaceholderText("详细描述你想要的故事...\n\n描述越详细，AI生成越精准")
        self.desc_text.setMaximumHeight(200)
        desc_layout.addWidget(self.desc_text)
        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)
        
        self.create_btn = QPushButton("🚀 创建项目")
        self.create_btn.clicked.connect(self.create_project)
        self.create_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 12px 30px;
                         font-size: 15px; font-weight: bold; border-radius: 8px; border: none; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.create_btn.setMinimumHeight(45)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.create_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "📋 项目设置")
    
    def create_outline_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        btn_layout = QHBoxLayout()
        self.gen_outline_btn = QPushButton("🎯 生成大纲")
        self.gen_outline_btn.clicked.connect(self.generate_outline)
        self.gen_outline_btn.setStyleSheet("background: #2196F3; color: white; font-weight: bold;")
        btn_layout.addWidget(self.gen_outline_btn)
        
        self.gen_chapters_btn = QPushButton("📑 生成章节规划")
        self.gen_chapters_btn.clicked.connect(self.generate_chapter_plan)
        btn_layout.addWidget(self.gen_chapters_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.outline_text = QTextEdit()
        self.outline_text.setPlaceholderText("大纲将显示在这里...\n先生成大纲，再生成角色和世界观，保证一致性")
        layout.addWidget(self.outline_text)
        
        self.outline_progress = QProgressBar()
        self.outline_progress.setVisible(False)
        layout.addWidget(self.outline_progress)
        
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "📝 大纲")
    
    def create_characters_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        btn_layout = QHBoxLayout()
        self.char_btn = QPushButton("👤 创建角色")
        self.char_btn.clicked.connect(self.create_character)
        self.char_btn.setStyleSheet("background: #FF9800; color: white; font-weight: bold;")
        btn_layout.addWidget(self.char_btn)
        
        self.world_btn = QPushButton("🌍 世界观设定")
        self.world_btn.clicked.connect(self.create_world_setting)
        self.world_btn.setStyleSheet("background: #9C27B0; color: white; font-weight: bold;")
        btn_layout.addWidget(self.world_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.char_text = QTextEdit()
        self.char_text.setPlaceholderText("角色和世界观将显示在这里...\n建议先生成大纲，再生成角色，保证人名一致")
        layout.addWidget(self.char_text)
        
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "👥 角色 & 世界观")
    
    def create_writing_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(6)
        
        # 模式选择
        mode_group = QGroupBox("写作模式")
        mode_layout = QHBoxLayout()
        
        self.single_mode = QRadioButton("单章写作")
        self.single_mode.setChecked(True)
        self.single_mode.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.single_mode)
        
        self.batch_mode = QRadioButton("批量写作")
        self.batch_mode.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.batch_mode)
        
        self.auto_mode = QRadioButton("自动写完整本")
        self.auto_mode.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.auto_mode)
        mode_layout.addStretch()
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        # 单章设置
        self.single_settings = QWidget()
        single_layout = QHBoxLayout()
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.addWidget(QLabel("章节号:"))
        self.chapter_num = QSpinBox()
        self.chapter_num.setMinimum(1)
        self.chapter_num.setMaximum(9999)
        self.chapter_num.setValue(1)
        single_layout.addWidget(self.chapter_num)
        single_layout.addWidget(QLabel("标题:"))
        self.chapter_title = QLineEdit()
        self.chapter_title.setPlaceholderText("留空自动生成...")
        single_layout.addWidget(self.chapter_title)
        self.auto_title_btn = QPushButton("🤖 自动生成")
        self.auto_title_btn.clicked.connect(self.auto_generate_title)
        self.auto_title_btn.setMaximumWidth(100)
        single_layout.addWidget(self.auto_title_btn)
        single_layout.addStretch()
        self.single_settings.setLayout(single_layout)
        layout.addWidget(self.single_settings)
        
        # 批量设置
        self.batch_settings = QWidget()
        self.batch_settings.setVisible(False)
        batch_layout = QHBoxLayout()
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.addWidget(QLabel("从第"))
        self.batch_start = QSpinBox()
        self.batch_start.setMinimum(1)
        self.batch_start.setMaximum(9999)
        self.batch_start.setValue(1)
        batch_layout.addWidget(self.batch_start)
        batch_layout.addWidget(QLabel("章到第"))
        self.batch_end = QSpinBox()
        self.batch_end.setMinimum(1)
        self.batch_end.setMaximum(9999)
        self.batch_end.setValue(5)
        batch_layout.addWidget(self.batch_end)
        batch_layout.addWidget(QLabel("章"))
        batch_layout.addStretch()
        self.batch_auto_title_cb = QCheckBox("自动生成标题")
        self.batch_auto_title_cb.setChecked(True)
        batch_layout.addWidget(self.batch_auto_title_cb)
        self.batch_continue_cb = QCheckBox("自动传递前情")
        self.batch_continue_cb.setChecked(True)
        batch_layout.addWidget(self.batch_continue_cb)
        self.batch_settings.setLayout(batch_layout)
        layout.addWidget(self.batch_settings)
        
        # 自动设置
        self.auto_settings = QWidget()
        self.auto_settings.setVisible(False)
        auto_layout = QHBoxLayout()
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.addWidget(QLabel("总章节数:"))
        self.auto_total = QSpinBox()
        self.auto_total.setMinimum(1)
        self.auto_total.setMaximum(9999)
        self.auto_total.setValue(100)
        auto_layout.addWidget(self.auto_total)
        auto_layout.addStretch()
        self.auto_settings.setLayout(auto_layout)
        layout.addWidget(self.auto_settings)
        
        # 上下文
        context_group = QGroupBox("写作上下文")
        context_layout = QHBoxLayout()
        
        left = QVBoxLayout()
        left.addWidget(QLabel("本章大纲:"))
        self.chapter_outline = QTextEdit()
        self.chapter_outline.setMaximumHeight(100)
        self.chapter_outline.setPlaceholderText("本章大纲或要点...")
        left.addWidget(self.chapter_outline)
        context_layout.addLayout(left)
        
        right = QVBoxLayout()
        right.addWidget(QLabel("前情提要:"))
        self.prev_summary = QTextEdit()
        self.prev_summary.setMaximumHeight(100)
        self.prev_summary.setPlaceholderText("前几章摘要...")
        right.addWidget(self.prev_summary)
        context_layout.addLayout(right)
        
        context_group.setLayout(context_layout)
        layout.addWidget(context_group)
        
        # 特殊要求
        extra_layout = QHBoxLayout()
        extra_layout.addWidget(QLabel("特殊要求:"))
        self.extra_input = QLineEdit()
        self.extra_input.setPlaceholderText("例如：要有战斗场面...")
        extra_layout.addWidget(self.extra_input)
        layout.addLayout(extra_layout)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.write_btn = QPushButton("✍️ 开始写作")
        self.write_btn.clicked.connect(self.start_writing)
        self.write_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 10px 20px;
                         font-size: 14px; font-weight: bold; border-radius: 5px; border: none; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        btn_layout.addWidget(self.write_btn)
        
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.clicked.connect(self.stop_writing)
        self.stop_btn.setVisible(False)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; padding: 10px 20px;
                         font-weight: bold; border-radius: 5px; }
        """)
        btn_layout.addWidget(self.stop_btn)
        
        self.polish_btn = QPushButton("✨ 润色")
        self.polish_btn.clicked.connect(self.polish_chapter)
        btn_layout.addWidget(self.polish_btn)
        
        self.check_btn = QPushButton("🔍 检查")
        self.check_btn.clicked.connect(self.check_consistency)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 进度
        self.write_progress = QProgressBar()
        self.write_progress.setVisible(False)
        layout.addWidget(self.write_progress)
        
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
        
        # 输出
        output_header = QHBoxLayout()
        output_header.addWidget(QLabel("📄 写作输出:"))
        output_header.addStretch()
        self.word_count_label = QLabel("字数: 0")
        output_header.addWidget(self.word_count_label)
        layout.addLayout(output_header)
        
        self.chapter_output = QTextEdit()
        self.chapter_output.setPlaceholderText("生成的章节内容...")
        self.chapter_output.textChanged.connect(
            lambda: self.word_count_label.setText(f"字数: {len(self.chapter_output.toPlainText())}")
        )
        layout.addWidget(self.chapter_output, 1)
        
        # 日志
        self.batch_log = QTextEdit()
        self.batch_log.setMaximumHeight(120)
        self.batch_log.setPlaceholderText("批量写作日志...")
        self.batch_log.setVisible(False)
        layout.addWidget(self.batch_log)
        
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "✍️ 写作")
    
    def create_preview_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        
        splitter = QSplitter(Qt.Horizontal)
        
        left = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.addWidget(QLabel("📑 章节列表:"))
        self.chapter_list = QListWidget()
        self.chapter_list.itemClicked.connect(self.on_chapter_selected)
        left_layout.addWidget(self.chapter_list)
        
        list_btns = QHBoxLayout()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh_chapter_list)
        list_btns.addWidget(refresh_btn)
        delete_btn = QPushButton("🗑 删除")
        delete_btn.clicked.connect(self.delete_chapter)
        list_btns.addWidget(delete_btn)
        left_layout.addLayout(list_btns)
        
        self.total_words_label = QLabel("总字数: 0")
        left_layout.addWidget(self.total_words_label)
        left.setLayout(left_layout)
        splitter.addWidget(left)
        
        right = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.addWidget(QLabel("📖 内容:"))
        self.preview_text = QTextBrowser()
        right_layout.addWidget(self.preview_text)
        right.setLayout(right_layout)
        splitter.addWidget(right)
        
        splitter.setSizes([250, 750])
        layout.addWidget(splitter)
        
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "📖 预览")
    
    # ============ 配置相关 ============
    
    def init_config(self):
        config = self.config_manager.load()
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        model_name = config.get("model_name", "")
        
        if api_key and base_url and model_name:
            try:
                self.setup_ai_model(config)
            except Exception as e:
                self.statusBar.showMessage(f"⚠️ 自动连接失败: {e}")
        else:
            self.statusBar.showMessage("💡 请点击「⚙ 配置AI」设置模型")
    
    def show_api_dialog(self):
        dialog = ApiKeyDialog(self, self.config_manager.get())
        if dialog.exec_() == QDialog.Accepted:
            config = dialog.get_config()
            if config["api_key"] and config["base_url"] and config["model_name"]:
                try:
                    self.setup_ai_model(config)
                    self.config_manager.update(**config)
                    QMessageBox.information(self, "成功", "✅ 连接成功！")
                except Exception as e:
                    QMessageBox.critical(self, "失败", str(e))
    
    def setup_ai_model(self, config):
        self.ai_model = ModelFactory.create_model(
            api_key=config["api_key"],
            model_name=config["model_name"],
            base_url=config["base_url"]
        )
        self.engine = NovelEngine(self.ai_model)
        self.model_label.setText(f" ✅ {config['model_name']}")
        self.model_label.setStyleSheet("color: green; font-weight: bold;")
        self.statusBar.showMessage(f"✅ 已连接: {config['base_url']} | {config['model_name']}")
    
    # ============ 项目操作 ============
    
    def create_project(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先配置AI模型")
            return
        
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入书名")
            return
        
        desc = self.desc_text.toPlainText().strip()
        if not desc:
            QMessageBox.warning(self, "提示", "请输入小说描述")
            return
        
        self.engine.set_basic_info(
            title=title,
            novel_type=self.type_combo.currentText(),
            tone=self.tone_combo.currentText(),
            description=desc,
            perspective=self.perspective_combo.currentText()
        )
        
        self.statusBar.showMessage(f"✅ 项目创建: 《{title}》")
        self.tab_widget.setCurrentIndex(1)
    
    def save_project(self):
        if not self.engine:
            return
        os.makedirs("novels", exist_ok=True)
        name = self.engine.novel_data.get("title", "未命名")
        path, _ = QFileDialog.getSaveFileName(self, "保存", f"novels/{name}.json", "JSON (*.json)")
        if path:
            self.engine.save_project(path)
            self.statusBar.showMessage(f"💾 已保存: {path}")
    
    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开", "novels/", "JSON (*.json)")
        if not path:
            return
        
        if not self.ai_model:
            config = self.config_manager.get()
            if config.get("api_key"):
                self.setup_ai_model(config)
            else:
                QMessageBox.warning(self, "提示", "请先配置AI模型")
                return
        
        try:
            self.engine = NovelEngine(self.ai_model)
            self.engine.load_project(path)
            data = self.engine.novel_data
            self.title_input.setText(data.get("title", ""))
            self.type_combo.setCurrentText(data.get("type", ""))
            self.tone_combo.setCurrentText(data.get("tone", ""))
            self.desc_text.setText(data.get("description", ""))
            
            # 恢复大纲、角色等
            if data.get("outline_info"):
                self.outline_text.setText(data["outline_info"])
            if data.get("characters_info"):
                self.char_text.setText(data["characters_info"])
            
            self.refresh_chapter_list()
            self.statusBar.showMessage(f"📂 已加载: {path}")
            self.tab_widget.setCurrentIndex(4)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
    
    def export_novel(self):
        if not self.engine or not self.engine.novel_data.get("chapters"):
            QMessageBox.warning(self, "提示", "没有可导出的内容")
            return
        
        name = self.engine.novel_data.get("title", "未命名")
        path, _ = QFileDialog.getSaveFileName(self, "导出", f"{name}.txt", "TXT (*.txt)")
        if not path:
            return
        
        novel = self.engine.novel_data
        chapters = sorted(novel["chapters"], key=lambda x: x.get("number", 0))
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"《{novel.get('title', '')}》\n")
            f.write(f"类型：{novel.get('type', '')} | 风格：{novel.get('tone', '')}\n")
            f.write(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            for ch in chapters:
                f.write(f"\n{'─' * 50}\n")
                f.write(f"第{ch.get('number', '?')}章 {ch.get('title', '')}\n")
                f.write(f"{'─' * 50}\n\n")
                f.write(ch.get("content", ""))
                f.write("\n\n")
            total = sum(len(ch.get("content", "")) for ch in chapters)
            f.write(f"\n{'=' * 60}\n全书共{len(chapters)}章 | 总字数: {total:,}\n")
        
        self.statusBar.showMessage(f"📤 已导出: {path}")
        QMessageBox.information(self, "导出成功", f"总章节: {len(chapters)}\n总字数: {total:,}")
    
    # ============ AI生成功能 ============
    
    def _run_async(self, func, on_done, on_error=None):
        """异步执行"""
        self.worker = AIWorkerThread(func)
        self.worker.finished.connect(on_done)
        if on_error:
            self.worker.error.connect(lambda e: (on_error(e), self._reset_buttons()))
        else:
            self.worker.error.connect(lambda e: self.on_error(e))
        self.worker.start()
    
    def generate_outline(self):
        if not self.engine:
            return
        self.outline_progress.setVisible(True)
        self.outline_progress.setRange(0, 0)
        self.gen_outline_btn.setEnabled(False)
        self.statusBar.showMessage("🎯 正在生成大纲...")
        self._run_async(
            lambda: self.engine.generate_outline(),
            self.on_outline_done
        )
    
    def on_outline_done(self, result):
        self.outline_progress.setVisible(False)
        self.gen_outline_btn.setEnabled(True)
        if isinstance(result, str) and result.startswith("[Error]"):
            QMessageBox.critical(self, "生成失败", result)
            self.statusBar.showMessage("❌ 大纲生成失败")
        else:
            self.outline_text.setText(result)
            self.statusBar.showMessage("✅ 大纲生成完成！请点击「创建角色」基于大纲生成角色")
    
    def generate_chapter_plan(self):
        if not self.engine:
            return
        outline = self.outline_text.toPlainText()
        if not outline:
            QMessageBox.warning(self, "提示", "请先生成大纲")
            return
        self.gen_chapters_btn.setEnabled(False)
        self.statusBar.showMessage("📑 正在生成章节规划...")
        self._run_async(
            lambda: self.engine.generate_chapter_outlines(outline),
            lambda r: (
                self.outline_text.append("\n\n" + "="*50 + "\n章节规划\n" + "="*50 + "\n\n" + r),
                setattr(self.gen_chapters_btn, 'enabled', True),
                self.statusBar.showMessage("✅ 章节规划完成")
            )
        )
    
    def create_character(self):
        if not self.engine:
            return
        self.char_btn.setEnabled(False)
        self.statusBar.showMessage("👤 正在基于大纲创建角色...")
        self._run_async(
            lambda: self.engine.create_character(),
            lambda r: (
                self.char_text.setText(r),
                setattr(self.char_btn, 'enabled', True),
                self.statusBar.showMessage("✅ 角色创建完成"),
                self.tab_widget.setCurrentIndex(2)
            )
        )
    
    def create_world_setting(self):
        if not self.engine:
            return
        self.world_btn.setEnabled(False)
        self.statusBar.showMessage("🌍 正在基于大纲创建世界观...")
        self._run_async(
            lambda: self.engine.create_world_setting(),
            lambda r: (
                self.char_text.append("\n\n" + "="*50 + "\n🌍 世界观设定\n" + "="*50 + "\n\n" + r),
                setattr(self.world_btn, 'enabled', True),
                self.statusBar.showMessage("✅ 世界观创建完成")
            )
        )
    
    def auto_generate_title(self):
        if not self.engine:
            return
        self.auto_title_btn.setEnabled(False)
        chapter_num = self.chapter_num.value()
        
        def gen():
            prompt = f"为小说第{chapter_num}章生成标题（8-15字），只返回标题。"
            messages = [{"role": "user", "content": prompt}]
            return self.engine.ai.chat(messages, temperature=0.9, max_tokens=50)
        
        self._run_async(
            gen,
            lambda t: (
                self.chapter_title.setText(t.strip().strip('"\'《》')),
                setattr(self.auto_title_btn, 'enabled', True)
            )
        )
    
    # ============ 写作功能 ============
    
    def on_mode_changed(self):
        self.single_settings.setVisible(self.single_mode.isChecked())
        self.batch_settings.setVisible(self.batch_mode.isChecked())
        self.auto_settings.setVisible(self.auto_mode.isChecked())
    
    def start_writing(self):
        if not self.engine:
            QMessageBox.warning(self, "提示", "请先配置AI并创建项目")
            return
        
        if self.single_mode.isChecked():
            self._write_single()
        elif self.batch_mode.isChecked():
            self._write_batch()
        else:
            self._write_auto()
    
    def _write_single(self):
        chapter_num = self.chapter_num.value()
        title = self.chapter_title.text().strip()
        
        if not title:
            self.auto_generate_title()
            QMessageBox.information(self, "提示", "标题已自动生成，确认后再次点击写作")
            return
        
        self._set_writing_state(True)
        
        def do_write():
            return self.engine.write_chapter(
                chapter_num=chapter_num,
                chapter_title=title,
                chapter_outline=self.chapter_outline.toPlainText(),
                previous_summary=self.prev_summary.toPlainText(),
                extra_instructions=self.extra_input.text()
            )
        
        self._run_async(do_write, self._on_single_done)
    
    def _on_single_done(self, content):
        self._set_writing_state(False)
        self.chapter_output.setText(content)
        self._save_chapter(self.chapter_num.value(), self.chapter_title.text(), content)
        self.refresh_chapter_list()
        self.statusBar.showMessage(f"✅ 第{self.chapter_num.value()}章完成 | 字数: {len(content)}")
    
    def _write_batch(self):
        start = self.batch_start.value()
        end = self.batch_end.value()
        
        if start > end:
            QMessageBox.warning(self, "提示", "起始章节不能大于结束章节")
            return
        
        count = end - start + 1
        reply = QMessageBox.question(
            self, "确认",
            f"将连续写作第{start}-{end}章，共{count}章。\n预计{count}~{count*3}分钟。\n\n请确保已生成大纲和角色设定！",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        self._start_batch_writing(start, end)
    
    def _write_auto(self):
        total = self.auto_total.value()
        
        reply = QMessageBox.question(
            self, "确认",
            f"将自动写完整本，共{total}章。\n预计{total}~{total*3}分钟。\n\n请确保已生成大纲和角色设定！",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        
        self._start_batch_writing(1, total)
    
    def _start_batch_writing(self, start, end):
        """启动批量写作"""
        self.is_writing = True
        self._set_writing_state(True, batch=True)
        
        total = end - start + 1
        self.write_progress.setRange(0, total)
        self.write_progress.setValue(0)
        self.batch_log.setVisible(True)
        self.batch_log.clear()
        self.batch_log.append(f"📚 开始写作：第{start}-{end}章，共{total}章\n")
        
        # 收集大纲和角色信息
        outline_text = self.outline_text.toPlainText() if hasattr(self, 'outline_text') else ""
        char_info = self.engine.novel_data.get("characters_info", "") if self.engine else ""
        
        settings = {
            "outline": outline_text,
            "characters": char_info,
            "prev_summary": self.prev_summary.toPlainText(),
            "extra": self.extra_input.text(),
            "auto_title": self.batch_auto_title_cb.isChecked() if self.batch_mode.isChecked() else True,
            "auto_continue": self.batch_continue_cb.isChecked() if self.batch_mode.isChecked() else True
        }
        
        self.batch_controller = BatchWriterController(
            self.engine, (start, end), settings
        )
        self.batch_controller.chapter_done.connect(self._on_batch_chapter_done)
        self.batch_controller.progress.connect(self._on_batch_progress)
        self.batch_controller.all_done.connect(self._on_batch_all_done)
        self.batch_controller.write_error.connect(self._on_batch_error)
        self.batch_controller.auto_saved.connect(
            lambda p: self.batch_log.append(f"💾 自动保存: {p}")
        )
        
        self.batch_thread = QThread()
        self.batch_controller.moveToThread(self.batch_thread)
        self.batch_thread.started.connect(self.batch_controller.run)
        self.batch_thread.start()
    
    def _on_batch_chapter_done(self, num, title, content):
        self.chapter_output.setText(content)
        self._save_chapter(num, title, content)
        self.batch_log.append(f"✅ 第{num}章《{title}》完成 ({len(content)}字)")
        # 自动滚动到底部
        scrollbar = self.batch_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_batch_progress(self, current, total, msg):
        self.write_progress.setValue(current)
        self.progress_label.setText(msg)
        self.progress_label.setVisible(True)
    
    def _on_batch_all_done(self):
        self._set_writing_state(False, batch=True)
        self.batch_log.append("\n🎉 全部完成！")
        self.refresh_chapter_list()
        self.statusBar.showMessage("✅ 批量写作完成")
        self.tab_widget.setCurrentIndex(4)
        QTimer.singleShot(1000, self._cleanup_batch)
    
    def _on_batch_error(self, chapter_num, error_msg):
        self.batch_log.append(f"❌ 第{chapter_num}章出错: {error_msg[:200]}")
        scrollbar = self.batch_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def stop_writing(self):
        if self.batch_controller:
            self.batch_controller.stop()
        self.is_writing = False
        self.batch_log.append("⏹ 正在停止...请等待当前章节写完")
        self.statusBar.showMessage("⏹ 正在停止...")
    
    def _cleanup_batch(self):
        if self.batch_controller:
            self.batch_controller.deleteLater()
            self.batch_controller = None
        
        if self.batch_thread:
            if self.batch_thread.isRunning():
                self.batch_thread.quit()
                if not self.batch_thread.wait(5000):
                    self.batch_thread.terminate()
                    self.batch_thread.wait(3000)
            self.batch_thread.deleteLater()
            self.batch_thread = None
        
        self.is_writing = False
    
    def closeEvent(self, event):
        self.stop_writing()
        self._cleanup_batch()
        time.sleep(0.5)
        event.accept()
    
    def _set_writing_state(self, writing: bool, batch: bool = False):
        self.is_writing = writing
        self.write_btn.setVisible(not writing)
        self.stop_btn.setVisible(writing)
        self.write_progress.setVisible(writing)
        self.progress_label.setVisible(writing)
        
        if not writing:
            self.write_progress.setValue(0)
            self.progress_label.setText("")
    
    def _save_chapter(self, num, title, content):
        if not self.engine:
            return
        chapters = self.engine.novel_data.get("chapters", [])
        chapter_data = {
            "number": num,
            "title": title,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        for i, ch in enumerate(chapters):
            if ch["number"] == num:
                chapters[i] = chapter_data
                return
        chapters.append(chapter_data)
        self.engine.novel_data["chapters"] = chapters
    
    def polish_chapter(self):
        text = self.chapter_output.toPlainText()
        if not text or not self.engine:
            return
        self.statusBar.showMessage("✨ 正在润色...")
        self._run_async(
            lambda: self.engine.polish_text(text),
            lambda r: (
                self.chapter_output.setText(r),
                self.statusBar.showMessage("✅ 润色完成")
            )
        )
    
    def check_consistency(self):
        text = self.chapter_output.toPlainText()
        if not text or not self.engine:
            return
        self.statusBar.showMessage("🔍 正在检查...")
        self._run_async(
            lambda: self.engine.check_consistency(text, self.prev_summary.toPlainText()),
            lambda r: (
                QMessageBox.information(self, "检查结果", r),
                self.statusBar.showMessage("✅ 检查完成")
            )
        )
    
    # ============ 预览功能 ============
    
    def refresh_chapter_list(self):
        self.chapter_list.clear()
        if not self.engine:
            return
        chapters = sorted(self.engine.novel_data.get("chapters", []),
                         key=lambda x: x.get("number", 0))
        total_words = 0
        for ch in chapters:
            content = ch.get("content", "")
            total_words += len(content)
            self.chapter_list.addItem(
                f"第{ch['number']}章 {ch.get('title', '')} ({len(content)}字)"
            )
        self.total_words_label.setText(f"总章节: {len(chapters)} | 总字数: {total_words:,}")
    
    def on_chapter_selected(self, item):
        if not self.engine:
            return
        idx = self.chapter_list.row(item)
        chapters = sorted(self.engine.novel_data.get("chapters", []),
                         key=lambda x: x.get("number", 0))
        if idx < len(chapters):
            ch = chapters[idx]
            self.preview_text.setHtml(f"""
                <h2>第{ch['number']}章 {ch.get('title', '')}</h2>
                <p style='color:#888;'>字数: {len(ch.get('content', ''))}</p>
                <hr>
                <pre style='white-space:pre-wrap;font-size:14px;line-height:1.8;'>
{ch.get('content', '')}
                </pre>
            """)
    
    def delete_chapter(self):
        item = self.chapter_list.currentItem()
        if not item or not self.engine:
            return
        if QMessageBox.question(self, "确认", f"删除「{item.text()}」？",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            idx = self.chapter_list.row(item)
            chapters = sorted(self.engine.novel_data.get("chapters", []),
                            key=lambda x: x.get("number", 0))
            if idx < len(chapters):
                del self.engine.novel_data["chapters"][idx]
                self.refresh_chapter_list()
                self.preview_text.clear()
    
    # ============ 错误处理 ============
    
    def _reset_buttons(self):
        self.gen_outline_btn.setEnabled(True)
        self.gen_chapters_btn.setEnabled(True)
        self.char_btn.setEnabled(True)
        self.world_btn.setEnabled(True)
        self.auto_title_btn.setEnabled(True)
    
    def on_error(self, error_msg):
        self._reset_buttons()
        self._set_writing_state(False)
        self.outline_progress.setVisible(False)
        QMessageBox.critical(self, "错误", error_msg[:500])
        self.statusBar.showMessage(f"❌ 错误: {error_msg[:100]}...")


# ============ 程序入口 ============
def main():
    print("=" * 60)
    print("  📚 AI小说写作软件")
    print("  支持任何OpenAI兼容API")
    print("=" * 60)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    
    window = MainWindow()
    window.show()
    
    if not os.path.exists("config.json"):
        QMessageBox.information(
            window, "欢迎",
            "👋 欢迎使用AI小说写作软件！\n\n"
            "使用流程：\n"
            "1. 配置AI模型\n"
            "2. 填写小说信息并创建项目\n"
            "3. 生成大纲\n"
            "4. 基于大纲生成角色\n"
            "5. 开始写作！"
        )
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()