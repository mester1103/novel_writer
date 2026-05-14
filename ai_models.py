"""
AI小说写作软件 - 通用模型接口
支持任何兼容OpenAI API的服务（LongCat、DeepSeek、硅基流动等）
"""

import json
import os
import time
from typing import List, Dict, Generator
from abc import ABC, abstractmethod
from datetime import datetime

# 检查openai库
try:
    from openai import OpenAI, Timeout
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class BaseAIModel(ABC):
    """AI模型基类"""
    
    def __init__(self, api_key: str, model_name: str, base_url: str):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
    
    @abstractmethod
    def chat(self, messages: List[Dict], temperature: float = 0.8,
             max_tokens: int = 4000) -> str:
        pass
    
    @abstractmethod
    def chat_stream(self, messages: List[Dict], temperature: float = 0.8,
                    max_tokens: int = 4000) -> Generator[str, None, None]:
        pass


class OpenAIModel(BaseAIModel):
    """通用OpenAI兼容接口模型
    
    支持：LongCat、OpenAI、DeepSeek、硅基流动、Ollama等
    """
    
    def __init__(self, api_key: str, model_name: str, base_url: str):
        if not OPENAI_AVAILABLE:
            raise ImportError("请安装openai库: pip install openai")
        
        super().__init__(api_key, model_name, base_url)
        
        # 确保base_url以/v1结尾
        if base_url and not base_url.rstrip('/').endswith('/v1'):
            if '/v1/' not in base_url:
                base_url = base_url.rstrip('/') + '/v1'
        
        # 设置超时和重试
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=Timeout(connect=15.0, read=180.0, write=15.0, pool=15.0),
            max_retries=2
        )
    
    def chat(self, messages: List[Dict], temperature: float = 0.8,
             max_tokens: int = 4000) -> str:
        """发送聊天请求（兼容多种返回格式）"""
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                # 尝试多种方式提取内容
                content = self._extract_content(response)
                
                if content and len(content.strip()) > 0:
                    return content
                else:
                    raise Exception("提取的内容为空")
                    
            except Exception as e:
                error_msg = str(e)
                
                # 最后一次尝试，返回错误
                if attempt == 2:
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        return "[Error] API密钥无效，请检查"
                    elif "403" in error_msg:
                        return "[Error] 无权访问此模型，请检查API密钥权限"
                    elif "404" in error_msg:
                        return f"[Error] 模型 '{self.model_name}' 未找到"
                    elif "429" in error_msg:
                        return "[Error] 请求太频繁，请稍后重试"
                    elif "timeout" in error_msg.lower() or "timed" in error_msg.lower():
                        return "[Error] 请求超时，请检查网络"
                    elif "Connection" in error_msg or "connect" in error_msg.lower():
                        return f"[Error] 无法连接到 {self.base_url}"
                    elif "balance" in error_msg or "quota" in error_msg or "insufficient" in error_msg:
                        return "[Error] API余额不足"
                    else:
                        return f"[Error] {error_msg[:200]}"
                
                # 重试前等待
                wait_time = (attempt + 1) * 3
                print(f"⚠️ 第{attempt+1}次失败，{wait_time}秒后重试...")
                time.sleep(wait_time)
        
        return "[Error] 所有重试均失败"
    
    def _extract_content(self, response) -> str:
        """从响应中提取内容（兼容多种格式）"""
        # 标准OpenAI格式
        try:
            if hasattr(response, 'choices') and response.choices:
                choice = response.choices[0]
                if hasattr(choice, 'message') and choice.message:
                    if hasattr(choice.message, 'content') and choice.message.content:
                        return choice.message.content
                if hasattr(choice, 'text') and choice.text:
                    return choice.text
        except:
            pass
        
        # 字典格式
        if isinstance(response, dict):
            try:
                return response['choices'][0]['message']['content']
            except:
                pass
            try:
                return response.get('content', '')
            except:
                pass
            try:
                return response.get('text', '')
            except:
                pass
        
        # 字符串格式
        if isinstance(response, str):
            return response
        
        # 其他属性
        try:
            if hasattr(response, 'content'):
                return response.content
        except:
            pass
        
        # 最后尝试转字符串
        try:
            return str(response)
        except:
            pass
        
        return None
    
    def chat_stream(self, messages: List[Dict], temperature: float = 0.8,
                    max_tokens: int = 4000) -> Generator[str, None, None]:
        """流式聊天"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            for chunk in stream:
                try:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                except:
                    pass
        except Exception as e:
            yield f"[Error] {str(e)}"


class ModelFactory:
    """模型工厂"""
    
    @classmethod
    def create_model(cls, api_key: str, model_name: str, base_url: str) -> OpenAIModel:
        """创建模型实例"""
        if not api_key:
            raise ValueError("请填写API密钥")
        if not model_name:
            raise ValueError("请填写模型名称")
        if not base_url:
            raise ValueError("请填写API地址")
        
        return OpenAIModel(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url
        )
    
    @classmethod
    def test_connection(cls, api_key: str, model_name: str, base_url: str) -> tuple:
        """测试连接
        
        Returns:
            (success: bool, message: str)
        """
        try:
            model = cls.create_model(api_key, model_name, base_url)
            response = model.chat(
                messages=[{"role": "user", "content": "请回复'连接成功'"}],
                max_tokens=50
            )
            if response.startswith("[Error]"):
                return False, response.replace("[Error] ", "")
            return True, f"✅ 连接成功！\n模型: {model_name}\n响应: {response[:100]}"
        except Exception as e:
            return False, str(e)


# ============ 配置管理 ============
class ConfigManager:
    """配置管理器"""
    
    DEFAULT_CONFIG = {
        "api_key": "",
        "model_name": "",
        "base_url": "",
        "note": "请填写你的API信息",
        "created_at": "",
        "updated_at": "",
        "settings": {
            "temperature": 0.8,
            "max_tokens": 4000,
            "auto_save": True
        },
        "presets": [
            {"name": "LongCat", "base_url": "https://api.longcat.chat", "model_name": ""},
            {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "model_name": "deepseek-chat"},
            {"name": "硅基流动", "base_url": "https://api.siliconflow.cn", "model_name": "Qwen/Qwen2.5-7B-Instruct"},
            {"name": "Ollama本地", "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b"},
        ]
    }
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = None
    
    def load(self) -> dict:
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                return self.config
            except:
                pass
        
        self.config = self.DEFAULT_CONFIG.copy()
        self.config["created_at"] = datetime.now().isoformat()
        self.config["updated_at"] = datetime.now().isoformat()
        self.save()
        return self.config
    
    def save(self):
        if self.config:
            self.config["updated_at"] = datetime.now().isoformat()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
    
    def get(self) -> dict:
        if self.config is None:
            self.load()
        return {
            "api_key": self.config.get("api_key", ""),
            "model_name": self.config.get("model_name", ""),
            "base_url": self.config.get("base_url", "")
        }
    
    def update(self, api_key: str, model_name: str, base_url: str):
        if self.config is None:
            self.load()
        self.config["api_key"] = api_key
        self.config["model_name"] = model_name
        self.config["base_url"] = base_url
        self.save()