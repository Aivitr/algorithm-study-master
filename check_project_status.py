#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多人教室语音识别优化方案 - 项目状态检查工具
Project Status Checker for Multi-room Classroom ASR Optimization
"""

import os
import json
from pathlib import Path
from datetime import datetime


class ProjectStatusChecker:
    """项目状态检查器"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.status = {
            "timestamp": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "stages": {},
            "files": {},
            "tests": {},
            "overall": {
                "completion_percentage": 0,
                "status": "⏳ 部分完成"
            }
        }
    
    def check_stage(self, stage_num: int, stage_name: str, files: list, 
                   checks: dict = None):
        """检查某个阶段的完成情况"""
        stage_key = f"stage_{stage_num}"
        self.status["stages"][stage_key] = {
            "name": stage_name,
            "files_required": {},
            "code_checks": checks or {}
        }
        
        for file_path in files:
            full_path = self.project_root / file_path
            exists = full_path.exists()
            self.status["stages"][stage_key]["files_required"][file_path] = {
                "exists": exists,
                "size_bytes": full_path.stat().st_size if exists else 0,
                "path": str(full_path)
            }
    
    def check_file_content(self, file_path: str, keywords: list) -> dict:
        """检查文件中的关键代码"""
        full_path = self.project_root / file_path
        result = {
            "file": file_path,
            "exists": full_path.exists(),
            "keywords_found": {}
        }
        
        if full_path.exists():
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                for keyword in keywords:
                    result["keywords_found"][keyword] = keyword in content
        
        return result
    
    def check_tests(self):
        """检查测试文件"""
        test_files = [
            ("test_speaker_lock.py", "Speaker Lock Tests"),
            ("test_cross_user_dedup.py", "Cross-User Dedup Tests"),
            ("test_speaker_volume_arbitration.py", "Volume Arbitration Tests")
        ]
        
        for test_file, test_name in test_files:
            full_path = self.project_root / test_file
            test_key = test_file.replace(".py", "")
            self.status["tests"][test_key] = {
                "name": test_name,
                "exists": full_path.exists(),
                "path": str(full_path)
            }
    
    def check_documentation(self):
        """检查文档文件"""
        doc_files = [
            "STAGE1_SPEAKER_LOCK_IMPLEMENTATION.md",
            "STAGE2_CROSS_USER_DEDUP_IMPLEMENTATION.md",
            "STAGE3_SPEAKER_VOLUME_ARBITRATION_IMPLEMENTATION.md",
            "STAGE4_FRONTEND_AUDIO_CONSTRAINT_IMPLEMENTATION.md",
            "STAGE4_TEST_CHECKLIST.md",
            "COMPLETE_SOLUTION_SUMMARY.md"
        ]
        
        self.status["files"]["documentation"] = {}
        for doc_file in doc_files:
            full_path = self.project_root / doc_file
            exists = full_path.exists()
            self.status["files"]["documentation"][doc_file] = {
                "exists": exists,
                "size_bytes": full_path.stat().st_size if exists else 0,
                "path": str(full_path)
            }
    
    def check_tools(self):
        """检查工具文件"""
        tool_files = [
            ("audio_constraint_test.html", "Stage 4 Interactive Testing Tool"),
            ("verify_stage4.py", "Stage 4 Verification Script")
        ]
        
        self.status["files"]["tools"] = {}
        for tool_file, tool_name in tool_files:
            full_path = self.project_root / tool_file
            exists = full_path.exists()
            self.status["files"]["tools"][tool_file] = {
                "name": tool_name,
                "exists": exists,
                "size_bytes": full_path.stat().st_size if exists else 0,
                "path": str(full_path)
            }
    
    def calculate_completion(self):
        """计算整体完成度"""
        total_items = 0
        completed_items = 0
        
        # 检查合格指标
        checks = {
            "documentation": self.status["files"].get("documentation", {}),
            "tools": self.status["files"].get("tools", {}),
            "tests": self.status["tests"]
        }
        
        for category, items in checks.items():
            for item_name, item_info in items.items():
                total_items += 1
                if item_info.get("exists"):
                    completed_items += 1
        
        # 检查代码集成
        server_py = self.project_root / "server.py"
        index_html = self.project_root / "index.html"
        
        stage_checks = 0
        stage_complete = 0
        
        # 检查各阶段特征代码
        if server_py.exists():
            with open(server_py, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                stage_checks += 4
                
                if "try_acquire_speaker_lock" in content:
                    stage_complete += 1  # Stage 1
                if "check_cross_user_duplicate" in content:
                    stage_complete += 1  # Stage 2
                if "get_speaker_confidence" in content:
                    stage_complete += 1  # Stage 3
                if "quality_score" in content:
                    stage_complete += 1  # Stage 4 (backend)
        
        if index_html.exists():
            with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if "echoCancellation: true" in content:
                    completed_items += 1  # Stage 4 (frontend)
                    total_items += 1
        
        # 计算百分比
        total_items += stage_checks
        completed_items += stage_complete
        
        if total_items > 0:
            percentage = (completed_items / total_items) * 100
            self.status["overall"]["completion_percentage"] = round(percentage, 1)
            
            if percentage >= 90:
                self.status["overall"]["status"] = "✅ 几乎完成"
            elif percentage >= 75:
                self.status["overall"]["status"] = "🟡 大部分完成"
            elif percentage >= 50:
                self.status["overall"]["status"] = "🔄 部分完成"
            else:
                self.status["overall"]["status"] = "⏳ 初期阶段"
    
    def generate_report(self) -> str:
        """生成文本报告"""
        lines = []
        lines.append("\n" + "="*80)
        lines.append("🎤 多人教室语音识别优化方案 - 项目状态检查")
        lines.append("="*80 + "\n")
        
        # 总体状态
        lines.append(f"📊 项目总体状态: {self.status['overall']['status']}")
        lines.append(f"📈 完成度: {self.status['overall']['completion_percentage']}%\n")
        
        # 文档完成情况
        lines.append("📚 文档文件:")
        for doc_file, info in self.status["files"].get("documentation", {}).items():
            status = "✅" if info["exists"] else "❌"
            size_kb = info["size_bytes"] / 1024 if info["size_bytes"] > 0 else 0
            lines.append(f"  {status} {doc_file:55} ({size_kb:6.1f} KB)")
        
        # 工具完成情况
        lines.append("\n🔧 工具文件:")
        for tool_file, info in self.status["files"].get("tools", {}).items():
            status = "✅" if info["exists"] else "❌"
            size_kb = info["size_bytes"] / 1024 if info["size_bytes"] > 0 else 0
            lines.append(f"  {status} {tool_file:55} ({size_kb:6.1f} KB)")
        
        # 测试完成情况
        lines.append("\n🧪 测试文件:")
        for test_name, info in self.status["tests"].items():
            status = "✅" if info["exists"] else "❌"
            lines.append(f"  {status} {info['name']:53} ({test_name})")
        
        # 阶段特征代码检查
        lines.append("\n🛠️  核心代码集成情况:")
        
        stage_info = [
            ("阶段1", "try_acquire_speaker_lock", "发言人锁机制"),
            ("阶段2", "check_cross_user_duplicate", "跨用户去重"),
            ("阶段3", "get_speaker_confidence", "音量仲裁"),
            ("阶段4", "echoCancellation: true", "前端音频约束")
        ]
        
        for stage, keyword, desc in stage_info:
            status = "✅" if keyword in self._get_codebase_content() else "❌"
            lines.append(f"  {status} {stage:8} - {desc:30} ({keyword})")
        
        lines.append(f"\n⏰ 检查时间: {self.status['timestamp']}")
        lines.append("="*80 + "\n")
        
        return "\n".join(lines)
    
    def _get_codebase_content(self) -> str:
        """获取所有代码库内容"""
        content = ""
        for file in self.project_root.glob("*.py"):
            try:
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content += f.read()
            except:
                pass
        
        for file in self.project_root.glob("*.html"):
            try:
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content += f.read()
            except:
                pass
        
        return content
    
    def save_json_report(self, output_file: str = None):
        """保存JSON格式的报告"""
        if output_file is None:
            output_file = self.project_root / "PROJECT_STATUS_REPORT.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.status, f, indent=2, ensure_ascii=False)
        
        return output_file
    
    def check_all(self):
        """执行所有检查"""
        self.check_documentation()
        self.check_tools()
        self.check_tests()
        self.calculate_completion()
        return self.status


def main():
    """主函数"""
    project_root = Path(__file__).parent
    
    print("\n🔍 正在检查项目状态...\n")
    
    checker = ProjectStatusChecker(str(project_root))
    checker.check_all()
    
    # 生成并打印报告
    report = checker.generate_report()
    print(report)
    
    # 保存JSON报告
    json_file = checker.save_json_report()
    print(f"✅ JSON报告已保存: {json_file}\n")
    
    # 返回完成度
    return checker.status["overall"]["completion_percentage"]


if __name__ == "__main__":
    main()
