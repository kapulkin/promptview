from anthropic import BaseModel
from pydantic import Field
import pytest
import pytest_asyncio
from promptview import view, prompt
from promptview.llms.utils.action_manager import Actions
from promptview.prompt.mvc import render_block

class TestAction(BaseModel):
        """use this if the user asks"""
        text: str = Field(..., title="Text", description="write a funny sentence about cats")
        
class TestAction2(BaseModel):
    """use this if the user asks"""
    text: str = Field(..., title="Text", description="write a funny sentence about dogs")
    
class TestAction3(BaseModel):
    """use this if the user asks"""
    _title="test_title_action"
    text: str = Field(..., title="Text", description="write a funny sentence about birds")



def test_tool_openai_serialization():

    tools = Actions(snake_case=True, actions=[TestAction, TestAction2, TestAction3])    
    openai_tools = tools.to_openai()
    assert len(openai_tools) == 3
    assert openai_tools[0]["function"]["name"] == "test_action"
    assert openai_tools[1]["function"]["name"] == "test_action2"
    assert openai_tools[2]["function"]["name"] == "test_title_action"

    tools = Actions(snake_case=False, actions=[TestAction, TestAction2, TestAction3])    
    openai_tools = tools.to_openai()
    assert len(openai_tools) == 3
    assert openai_tools[0]["function"]["name"] == "TestAction"
    assert openai_tools[1]["function"]["name"] == "TestAction2"
    assert openai_tools[2]["function"]["name"] == "test_title_action"


def test_tool_anthropic_serialization():
    tools = Actions(snake_case=True, actions=[TestAction, TestAction2, TestAction3])    
    anthropic_tools = tools.to_anthropic()
    assert len(anthropic_tools) == 3
    assert anthropic_tools[0]["name"] == "test_action"
    assert anthropic_tools[1]["name"] == "test_action2"
    assert anthropic_tools[2]["name"] == "test_title_action"   
    
    tools = Actions(snake_case=False, actions=[TestAction, TestAction2, TestAction3])
    anthropic_tools = tools.to_anthropic()
    assert len(anthropic_tools) == 3
    assert anthropic_tools[0]["name"] == "TestAction"
    assert anthropic_tools[1]["name"] == "TestAction2"
    assert anthropic_tools[2]["name"] == "test_title_action"


def test_tool_lookup():
    tools = Actions(snake_case=True, actions=[TestAction, TestAction2, TestAction3])    
    action = tools.get("test_action")
    assert action == TestAction
    action = tools.get("test_action2")
    assert action == TestAction2
    action = tools.get("test_title_action")
    assert action == TestAction3
    tools = Actions(snake_case=False, actions=[TestAction, TestAction2, TestAction3])    
    action = tools.get("TestAction")
    assert action == TestAction
    action = tools.get("TestAction2")
    assert action == TestAction2
    action = tools.get("test_title_action")
    
    