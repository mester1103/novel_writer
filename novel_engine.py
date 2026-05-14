"""
小说写作引擎
"""

import json
import os
from typing import Optional
from datetime import datetime
from ai_models import BaseAIModel


class NovelEngine:
    """小说写作引擎"""
    
    def __init__(self, ai_model: BaseAIModel):
        self.ai = ai_model
        self.novel_data = {
            "title": "",
            "type": "",
            "tone": "",
            "description": "",
            "perspective": "第三人称",
            "chapters": [],
            "characters_info": "",
            "world_setting_info": "",
            "outline_info": "",
            "created_at": datetime.now().isoformat()
        }
    
    def set_basic_info(self, title: str, novel_type: str, tone: str,
                       description: str, perspective: str = "第三人称"):
        """设置基本信息"""
        self.novel_data.update({
            "title": title,
            "type": novel_type,
            "tone": tone,
            "description": description,
            "perspective": perspective
        })
    
    def generate_outline(self, extra_requirements: str = "") -> str:
        """生成小说大纲"""
        novel = self.novel_data
        
        prompt = f"""为以下小说生成一个详细的大纲框架。

书名：《{novel['title']}》
类型：{novel['type']}
风格：{novel['tone']}
简介：{novel['description']}
{extra_requirements if extra_requirements else ''}

请按以下结构输出：
1. 故事主线（一句话概括）
2. 主角姓名（必须确定一个名字，后续不能改）
3. 三幕结构（开端20章、发展60章、结局20章）
4. 5个关键转折点
5. 主要角色关系
6. 3个重要伏笔

重要：主角姓名一旦确定，后续所有内容必须使用这个名字！"""

        messages = [
            {"role": "system", "content": "你是专业小说策划，回答结构清晰。主角名字一旦确定不可更改。"},
            {"role": "user", "content": prompt}
        ]
        
        result = self.ai.chat(messages, temperature=0.7, max_tokens=2500)
        self.novel_data["outline_info"] = result
        return result
    
    def generate_chapter_outlines(self, main_outline: str, total_chapters: int = 100) -> str:
        """生成章节规划"""
        prompt = f"""基于以下大纲，为前10章生成详细章节规划。

总大纲：
{main_outline[:2000]}

每章包含：
- 章节标题
- 核心情节（2-3句话）
- 该章要推进的角色发展

简洁即可，总共10章。"""

        messages = [
            {"role": "system", "content": "你是专业的章节规划师。"},
            {"role": "user", "content": prompt}
        ]
        return self.ai.chat(messages, temperature=0.6, max_tokens=2000)
    
    def create_character(self, character_desc: str = "") -> str:
        """创建角色"""
        outline = self.novel_data.get("outline_info", "")
        novel = self.novel_data
        
        if outline:
            prompt = f"""请基于以下小说大纲，创建3个主要角色。

小说类型：{novel['type']}
风格：{novel['tone']}

【大纲】
{outline[:2000]}

请创建：
1. 主角（姓名必须和大纲完全一致！）
2. 重要伙伴/导师
3. 主要反派/对手

每个角色包含：姓名、年龄、外貌、性格、背景、动机、与主线关系。
重要：主角姓名必须和大纲中出现的名字一模一样！"""

        else:
            prompt = f"""为以下小说创建3个主要角色。

小说：《{novel['title']}》
类型：{novel['type']}
简介：{novel['description']}

包含：姓名、年龄、外貌、性格、背景、动机。"""

        messages = [
            {"role": "system", "content": "你是专业角色设计师。角色姓名一旦确定不能更改。"},
            {"role": "user", "content": prompt}
        ]
        
        result = self.ai.chat(messages, temperature=0.7, max_tokens=2500)
        self.novel_data["characters_info"] = result
        return result
    
    def create_world_setting(self) -> str:
        """创建世界观"""
        outline = self.novel_data.get("outline_info", "")
        novel = self.novel_data
        
        if outline:
            prompt = f"""请基于大纲创建世界观。

【大纲】
{outline[:2000]}

设计：时代背景、力量体系、社会结构、重要地点。
严格基于大纲，不自行发挥。"""
        else:
            prompt = f"""为小说创建世界观。
类型：{novel['type']}
简介：{novel['description']}

设计：时代背景、力量体系、社会结构、重要地点。"""

        messages = [
            {"role": "system", "content": "你是世界观架构师，严格遵循大纲设定。"},
            {"role": "user", "content": prompt}
        ]
        
        result = self.ai.chat(messages, temperature=0.7, max_tokens=2000)
        self.novel_data["world_setting_info"] = result
        return result
    
    def write_chapter(self, chapter_num: int, chapter_title: str = "",
                      chapter_outline: str = "", previous_summary: str = "",
                      extra_instructions: str = "") -> str:
        """写作具体章节"""
        novel = self.novel_data
        
        # 收集角色和世界观信息
        char_info = novel.get("characters_info", "")
        world_info = novel.get("world_setting_info", "")
        outline_info = novel.get("outline_info", "")
        
        system_prompt = f"""你是一位畅销书作家，正在创作《{novel['title']}》。

【基本设定】
- 类型：{novel['type']}
- 风格：{novel['tone']}
- 视角：{novel['perspective']}
- 字数：3000-5000字

【角色设定（严格遵守）】
{char_info[:1500] if char_info else '按大纲设定'}

【世界观】
{world_info[:800] if world_info else '按大纲设定'}

【写作原则】
1. 角色姓名必须和设定完全一致，不能出现新名字
2. Show, don't tell
3. 对话自然，符合角色性格
4. 不要出现"在这个世界里"等解说
5. 避免AI味道，不要过度解释"""

        user_prompt = f"""写第{chapter_num}章：{chapter_title}

"""
        if previous_summary:
            user_prompt += f"【前情提要】\n{previous_summary[:800]}\n\n"
        if chapter_outline:
            user_prompt += f"【本章大纲】\n{chapter_outline[:1000]}\n\n"
        if extra_instructions:
            user_prompt += f"【特殊要求】\n{extra_instructions}\n\n"
        
        user_prompt += "请直接开始写正文："

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return self.ai.chat(messages, temperature=0.85, max_tokens=5000)
    
    def polish_text(self, text: str, style_guide: str = "") -> str:
        """润色文本"""
        prompt = f"""润色以下小说片段。

要求：消除重复用词、增强画面感、优化对话、保持原意。

原文：
{text}

润色后："""

        messages = [
            {"role": "system", "content": "你是专业文学编辑。"},
            {"role": "user", "content": prompt}
        ]
        return self.ai.chat(messages, temperature=0.5, max_tokens=4000)
    
    def check_consistency(self, chapter_text: str, prev_summary: str = "") -> str:
        """检查逻辑一致性"""
        prompt = f"""检查以下章节的逻辑问题。

【前文概要】
{prev_summary[:500] if prev_summary else '无'}

【本章内容】
{chapter_text[:3000]}

检查：角色名是否一致、时间线、前后矛盾、伏笔。
如有问题列位置和修改建议，无问题回复"通过"。"""

        messages = [
            {"role": "system", "content": "你是严格的小说编辑。"},
            {"role": "user", "content": prompt}
        ]
        return self.ai.chat(messages, temperature=0.3, max_tokens=1500)
    
    def save_project(self, filepath: str):
        """保存项目"""
        self.novel_data["updated_at"] = datetime.now().isoformat()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.novel_data, f, ensure_ascii=False, indent=2)
    
    def load_project(self, filepath: str):
        """加载项目"""
        with open(filepath, "r", encoding="utf-8") as f:
            self.novel_data = json.load(f)