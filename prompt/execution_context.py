import inspect
from abc import abstractmethod
from enum import Enum
from functools import wraps
from typing import (Any, Awaitable, Callable, Generator, Generic, List,
                    Literal, ParamSpec, Type, TypedDict, TypeVar, Union)

from promptview.llms.messages import (ActionCall, ActionMessage, AIMessage,
                                      BaseMessage, HumanMessage, MessageChunk)
from promptview.llms.tracer import RunTypes, Tracer
from promptview.llms.utils.action_manager import Actions
from promptview.prompt.mvc import ViewBlock, create_view_block
from promptview.prompt.types import PromptInputs, ToolChoiceParam
from promptview.state.context import Context
from pydantic import BaseModel, Field

P = ParamSpec("P")
# P = TypeVar("P")

# ExecutionLifecycle = Literal["start", "end", "error", "action", "response", "message", "view", "action_call", "chunk", "tracer"]

# ExecutionLifecycle = Literal["start", "render", "messages", "action_calls", "send_message", "finished", "error"]
class ExLifecycle(Enum):
    START = 0
    RENDER = 1
    INTERPRET = 2
    COMPLETE = 3
    ACTION_CALLS = 4
    SEND_MESSAGE = 5    
    FINISHED = 6
    ERROR = 7
    

ExecutionType = Literal["agent", "agent_prompt", "prompt", "tool"] 



class Execution(BaseModel):
    lifecycle_phase: ExLifecycle = ExLifecycle.START
    model: str | None = None
    prompt_name: str
    actions: Actions | None = None
    context: Context | None = None
    # root_block: ViewBlock = Field(default_factory=lambda: create_view_block([], "root"))
    root_block: ViewBlock | None = None
    messages: List[BaseMessage] | None = None
    response: AIMessage | ActionMessage | None = None
    is_stream: bool = False
    run_type: RunTypes
    ex_type: ExecutionType = "prompt"
    tool_choice: ToolChoiceParam | None = None
    
    parent: Union['Execution', None] = None
    action_call: ActionCall | None = None
    todo_action_calls: List[ActionCall] = []
    kwargs: Any
    
    error: Exception | None = None
    
    parent_tracer_run: Tracer | None = None
    tracer_run: Tracer | None = None
    is_traceable: bool = True
    
    class Config:
        arbitrary_types_allowed = True

    
    @property
    def action_calls(self) -> List[ActionCall]:
        if isinstance(self.response, AIMessage):
            if self.response.action_calls:
                return self.response.action_calls
        return []
    
    @property
    def did_finish(self):
        return self.lifecycle_phase == ExLifecycle.FINISHED
    
    
    def advance_lifecycle(self):
        if self.lifecycle_phase == ExLifecycle.START:
            if self.ex_type == "tool":
                self.lifecycle_phase = ExLifecycle.COMPLETE
            else:
                self.lifecycle_phase = ExLifecycle.RENDER
        elif self.lifecycle_phase == ExLifecycle.RENDER:
            if self.root_block:
                self.lifecycle_phase = ExLifecycle.INTERPRET
            else:
                raise ValueError("Root block is not set")
        elif self.lifecycle_phase == ExLifecycle.INTERPRET:
            if self.messages:
                self.lifecycle_phase = ExLifecycle.COMPLETE
        elif self.lifecycle_phase == ExLifecycle.COMPLETE:
            if self.ex_type == "agent" or self.ex_type == "prompt":
                if self.is_stream:
                    self.lifecycle_phase = ExLifecycle.FINISHED
                elif self.response:
                    if self.response.content:
                        self.lifecycle_phase = ExLifecycle.SEND_MESSAGE
                    elif isinstance(self.response, AIMessage) and self.response.action_calls:
                        self.lifecycle_phase = ExLifecycle.ACTION_CALLS
                        self.todo_action_calls = [a for a in self.response.action_calls]
                    else:
                        self.lifecycle_phase = ExLifecycle.FINISHED
            elif self.ex_type == "tool":
                self.lifecycle_phase = ExLifecycle.FINISHED
            else:
                raise ValueError(f"Invalid execution type: {self.ex_type}")
        elif self.lifecycle_phase == ExLifecycle.SEND_MESSAGE:
            assert self.response is not None
            assert self.response.content is not None
            
            if isinstance(self.response, AIMessage) and self.response.action_calls:
                self.lifecycle_phase = ExLifecycle.ACTION_CALLS
            else:
                self.lifecycle_phase = ExLifecycle.FINISHED
                
        elif self.lifecycle_phase == ExLifecycle.ACTION_CALLS:
            if not self.todo_action_calls:
                self.lifecycle_phase = ExLifecycle.FINISHED        
        else:
            raise ValueError(f"Invalid lifecycle phase: {self.lifecycle_phase}")
        # elif self.lifecycle_phase == ExLifecycle.FINISHED:
            
        # elif self.lifecycle_phase == ExLifecycle.ERROR:
            
        # else:
        #     raise ValueError(f"Invalid lifecycle phase: {self.lifecycle_phase}")
        

    def add_view(self, view: ViewBlock | List[ViewBlock] | HumanMessage | AIMessage | ActionMessage):
        if not isinstance(view, ViewBlock):
            view = create_view_block(view, self.prompt_name + '_output')
        # if self.root_block is None:
        #     self.root_block = view
        # else:
        #     self.root_block.add(view)
        if self.root_block is None:
            self.root_block = create_view_block([], 'root')        
        self.root_block.add(view)
        self.advance_lifecycle()
        #TODO
        # self.lifecycle_phase = ExLifecycle.INTERPRET
    
    
    def set_messages(self, messages: List[BaseMessage], actions: Actions):
        self.messages = messages
        self.actions = actions
        self.advance_lifecycle()
        #TODO 
        # self.lifecycle_phase = ExLifecycle.COMPLETE
            
            
    def add_response(self, response: ViewBlock | AIMessage | Any, is_stream: bool = False):
        self.is_stream = is_stream
        if isinstance(response, AIMessage):
            self.add_prompt_response(response)
        else:
            self.add_function_response(response)
        
        
    def add_prompt_response(self, response: AIMessage):
        if not self.tracer_run:
            raise ValueError("Tracer is not set")
        if self.response is not None:
            raise ValueError("Output is already set")            
        self.response = response        
        self.tracer_run.end_post(outputs={'output': response.raw})
        self.advance_lifecycle()
        #TODO
        # if self.ex_type == "agent" or self.ex_type == "prompt":
        #     if response.content:
        #         self.lifecycle_phase = ExLifecycle.SEND_MESSAGE
        #     elif response.action_calls:
        #         self.lifecycle_phase = ExLifecycle.ACTION_CALLS
        #         self.todo_action_calls = [a for a in response.action_calls]
        #     else:
        #         self.lifecycle_phase = ExLifecycle.FINISHED                
        # # elif self.ex_type == "prompt":
        # #     self.lifecycle_phase = ExLifecycle.FINISHED
        # elif self.ex_type == "tool":
        #     self.lifecycle_phase = ExLifecycle.FINISHED
        # else:
        #     raise ValueError(f"Invalid execution type: {self.ex_type}")
        
    
    def finish_action_call(self, action_call: ActionCall):
        for i, a in enumerate(self.todo_action_calls):
            if a.id == action_call.id:
                self.todo_action_calls.pop(i)
                break
        else:
            raise ValueError(f"Action call not found: {action_call}")    
        self.advance_lifecycle()
        #TODO 
        # if not self.todo_action_calls:
        #     self.lifecycle_phase = ExLifecycle.FINISHED
        
        
    def add_function_response(self, action_output: Any):
        if not self.tracer_run:
            raise ValueError("Tracer is not set")
        if self.response is not None:
            raise ValueError("Output is already set")
        if not self.action_call:
            raise ValueError("Action call is not set")
        if type(action_output) == str:
            action_output_str = action_output
        elif isinstance(action_output, BaseModel):
            action_output_str = action_output.model_dump_json()
        else:
            raise ValueError(f"Invalid action output ({type(action_output)}): {action_output}")
        response = ActionMessage(
            id=self.action_call.id,
            content=action_output_str,
        )
        self.response = response
        # self.tracer_run.add_outputs(response)
        self.tracer_run.end_post(outputs={'output': action_output_str})
        # self.tracer_run.end(outputs={'output': action_output_str})
        # self.tracer_run.end_run(outputs={'output': response})
        self.advance_lifecycle()
        #TODO 
        # self.lifecycle_phase = ExLifecycle.FINISHED
    
    
    
    def send_message(self):
        if not self.response:
            raise ValueError("Response is not set")
        if self.lifecycle_phase != ExLifecycle.SEND_MESSAGE:
            raise ValueError("not in send message phase")
        self.advance_lifecycle()
        #TODO
        # if self.response.action_calls:
        #     self.lifecycle_phase = ExLifecycle.ACTION_CALLS
        # else:
        #     self.lifecycle_phase = ExLifecycle.FINISHED
        return self.response
        
    def start(self):
        self.tracer_run = self.build_tracer()
        self.advance_lifecycle()
        #TODO
        # self.lifecycle_phase = ExLifecycle.RENDER
        return self.tracer_run
    
        
    def build_tracer(self):
        inputs = {}
        if self.kwargs:
            inputs["inputs"] = self.kwargs
        tracer_run = Tracer(
            is_traceable=self.is_traceable,
            tracer_run=self.parent_tracer_run,
            name=self.prompt_name,
            run_type=self.run_type,
            inputs=inputs
        )
        return tracer_run


class ExecutionContext(BaseModel):
    executions: List[Execution] = []
    prompt_name: str
    is_traceable: bool = True
    context: Context | None = None
    ex_type: ExecutionType = "prompt"
    run_type: RunTypes = "prompt"
    kwargs: Any = {}
    stack: List[Execution] = [] 
    parent_ctx: Union['ExecutionContext', None] = None   
    
    @property
    def curr_ex(self):
        if self.stack:
            return self.stack[-1]
        # if self.executions:
        #     return self.executions[-1]
        return None
    
    
    @property
    def response(self):
        if not self.executions:
            return None
        return self.executions[-1].response
    
    @property
    def lifecycle_phase(self):
        if self.curr_ex:
            return self.curr_ex.lifecycle_phase
        return ExLifecycle.FINISHED
    
    @property
    def action_calls(self) -> List[ActionCall]:
        if self.curr_ex:
            return self.curr_ex.action_calls
        return []
    
    @property
    def tool_choice(self):
        if self.curr_ex:
            return self.curr_ex.tool_choice
        return None
    
    @property
    def tracer_run(self):
        if self.curr_ex:
            return self.curr_ex.tracer_run
        return None
    
    def build_action_calls(self):
        action_calls = []
        
    
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        # if self.parent_ctx:
            # self.parent_ctx.merge_child(self)
        # if self.tracer_run:
            # self.tracer_run.end_run(exc_type, exc_value, traceback)
        return False 
        
        
    def add_view(self, view: List[ViewBlock] | ViewBlock | HumanMessage | AIMessage | ActionMessage):
        if not self.curr_ex:
            raise ValueError("No execution to add view")
        self.curr_ex.add_view(view)
        return self.curr_ex
    
    
    def get_views(self) -> ViewBlock:
        if self.curr_ex and self.curr_ex.root_block:
            return self.curr_ex.root_block
        raise ValueError("No execution to get views")
    
    def set_messages(self, messages: List[BaseMessage], actions: Actions):
        if not self.curr_ex:
            raise ValueError("No execution to add messages")
        self.curr_ex.set_messages(messages, actions)
        return self.curr_ex
    
    def get_messages(self) -> List[BaseMessage]:
        messages = []
        for ex in self.executions:
            
            if ex.ex_type == "tool":
                if ex.did_finish:
                    if ex.response:
                        messages.append(ex.response)
                    else:
                        raise ValueError("No response in tool execution")
                else:
                    if ex.messages:
                        messages.extend(ex.messages)
                    else:
                        raise ValueError("No messages in tool execution")
            else:
                if ex.messages:
                    messages.extend(ex.messages)
                if ex.response:
                    messages.append(ex.response)
        return messages  
    
    def get_actions(self) -> Actions | None:
        if self.curr_ex and self.curr_ex.actions:
            return self.curr_ex.actions
        return None
        # raise ValueError("No execution to get actions")
    
    def send_message(self)-> str:
        if self.curr_ex:
            response =  self.curr_ex.send_message()
            if not response.content:
                raise ValueError("No message to send")
            # if self.curr_ex.did_finish:
            #     self.stack.pop()
            self.manage_stack()
            return response.content
        else:
            raise ValueError("No execution to send message")
        
        
    def create_child(self, prompt_name: str, ex_type: ExecutionType="prompt", run_type: RunTypes = "prompt", kwargs: Any = {}):
        # if self.ex_type == "agent":
        #     if self.lifecycle_phase == ExLifecycle.ACTION_CALLS or action_call is not None:
        #         ex_type = "tool"
        #     else:
        #         ex_type = "agent_prompt"
        # else:
        #     ex_type = "prompt"

        # if self.lifecycle_phase == ExLifecycle.ACTION_CALLS:
        #     ex_type = "tool"
        
        
        ex_ctx = ExecutionContext(
            prompt_name=prompt_name,
            is_traceable=self.is_traceable,
            context=self.context,
            ex_type=ex_type,
            run_type=run_type,
            kwargs=kwargs,
            parent_ctx=self
        )                
        return ex_ctx
    
    def merge_child(self, ex_ctx: "ExecutionContext"):
        self.executions.extend(ex_ctx.executions)        
        if ex_ctx.lifecycle_phase != ExLifecycle.FINISHED:
            self.stack.extend(ex_ctx.stack)
        return self
    
    
    
    def start_execution(
        self, 
        prompt_name: str,         
        kwargs: Any, 
        run_type: RunTypes | None = None, 
        tool_choice: ToolChoiceParam | None= None,
        action_call: ActionCall | None = None,
        model: str | None = None, 
    ):
        # if self.ex_type == "agent":
        #     if self.lifecycle_phase == ExLifecycle.ACTION_CALLS or action_call is not None:
        #         ex_type = "tool"
        #     else:
        #         ex_type = "agent_prompt"
        # else:
        #     ex_type = "prompt"
        
        
        execution = Execution(
            prompt_name=prompt_name,
            model=model,
            kwargs=self.kwargs,
            run_type=run_type or self.run_type,
            context=self.context,
            # parent_tracer_run=self.curr_ex.tracer_run if self.curr_ex else None,
            parent_tracer_run=self.parent_ctx.tracer_run if self.parent_ctx else None,
            tool_choice=tool_choice,
            action_call=action_call,
            ex_type=self.ex_type,
        )                                
        execution.start()
        # if execution.ex_type == "agent_prompt":
        #     if self.executions:
        #         messages = self.get_message_history()
        #         execution.messages = messages
        #         execution.lifecycle_phase = ExLifecycle.COMPLETE
                
        self.executions.append(execution)
        self.stack.append(execution)
        return self

    
    def manage_stack(self):
        if self.curr_ex:
            if self.curr_ex.did_finish:
                ex = self.stack.pop()
                # if ex.tracer_run:
                #     ex.tracer_run.end_run()
        

    def add_response(self, response: Any, is_stream: bool = False):
        if not self.curr_ex:
            raise ValueError("No execution to add response")
        # if self.curr_ex.lifecycle_phase != ExLifecycle.COMPLETE:
        #     raise ValueError("Execution is not in complete phase")
        self.curr_ex.add_response(response, is_stream)
        self.manage_stack()
        return self.curr_ex
    
    
    
    def finish_action_call(self, action_call: ActionCall):
        if not self.curr_ex:
            raise ValueError("No execution to finish action calls")
        if self.curr_ex.lifecycle_phase != ExLifecycle.ACTION_CALLS:
            raise ValueError("Execution is not in action calls phase")
        self.curr_ex.finish_action_call(action_call)
        self.manage_stack()
        
        
        

    # def end_execution(self):
    #     if not self.curr_ex:
    #         raise ValueError("No execution to end")
    #     if self.curr_ex.lifecycle_phase != ExLifecycle.FINISHED:
    #         raise ValueError("Execution is not finished")
    #     self.stack.pop()
    #     # self.curr_ex.response = response
    #     # self.curr_ex.error = error
        
        
    
    
    


class BaseExecutionContext(BaseModel):
    name: str
    inputs: PromptInputs
    is_traceable: bool = True
    tracer_run: Tracer | None = None
    run_type: RunTypes
    children: List["BaseExecutionContext"] = []
    parent: Any | None = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __enter__(self):
        self.tracer_run = self.tracer()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.end_run()
        if self.tracer_run:
            self.tracer_run.end_run(exc_type, exc_value, traceback)
        return False
    
    @abstractmethod
    def end_run(self):
        raise NotImplementedError("end_run method must be implemented")
    
    @abstractmethod
    def tracer(self):
        raise NotImplementedError("tracer method must be implemented")
    


class LlmExecutionContext(BaseExecutionContext):
    model: str
    messages: List[BaseMessage] | None = None
    actions: Actions | None = None
    response: AIMessage | None = None
    chunks: List[MessageChunk] | None = None
    run_type: RunTypes = "llm"
    
    
    def push_chunk(self, chunk: MessageChunk):
        if self.chunks is None:
            self.chunks = []
        self.chunks.append(chunk)

    def tracer(self):
        inputs = {}
        if self.inputs.message:
            inputs["message"] = self.inputs.message.content
        if self.inputs.kwargs:
            inputs["input"] = self.inputs.kwargs
        return Tracer(
            is_traceable=self.is_traceable,
            tracer_run=self.inputs.tracer_run,
            name=self.name,
            run_type=self.run_type,
            inputs=inputs
        )  


class PromptExecutionContext2(BaseExecutionContext):
    # name: str   
    # inputs: PromptInputs
    # is_traceable: bool = True
    root_block: ViewBlock = Field(default_factory=lambda: create_view_block([], "root"))
    messages: List[BaseMessage] | None = None
    actions: Actions | None = None  
    chunks: List[MessageChunk] | None = None  
    # prompt_run: Tracer | None = None
    output: AIMessage | None = None   
    action_calls: List[ActionCall] = []

    
    def push_chunk(self, chunk: MessageChunk):
        if self.chunks is None:
            self.chunks = []
        self.chunks.append(chunk)
    
    def copy_ctx(self, with_views=False, with_messages=False, with_tracer=False):
        ctx = PromptExecutionContext2(
            name=self.name,
            is_traceable=self.is_traceable,
            inputs=self.inputs.model_copy(),
            run_type=self.run_type
        )        
        if with_views and self.root_block is not None:
            ctx.root_block = self.root_block.model_copy()
        if with_messages and self.messages is not None:
            ctx.messages = [m.model_copy() for m in self.messages]
        if with_tracer:
            ctx.tracer_run = self.tracer_run
        return ctx
    
    
    def iter_action_calls(self) -> Generator[ActionCall, str, None]:
        while self.action_calls:
            yield self.action_calls.pop(0)
    
    def end_run(self):
        if self.tracer_run and self.output:
            self.tracer_run.end_post(outputs={'output': self.output.raw})
        
    
    def extend_views(self, views: List[ViewBlock]):
        if self.root_block is None:
            raise ValueError("Root block is not set")
        self.root_block.extend(views)
        return self.root_block
    
    
    def tracer(self):
        inputs = {}
        if self.inputs.message:
            inputs["message"] = self.inputs.message.content
        if self.inputs.kwargs:
            inputs["input"] = self.inputs.kwargs
        parent_tracer = None
        if self.parent:
            parent_tracer = self.parent.tracer_run
        return Tracer(
            is_traceable=self.is_traceable,
            tracer_run=parent_tracer,
            name=self.name,
            run_type=self.run_type,
            inputs=inputs
        )
        
        
    def merge_ctx(self, ex_ctx: "ExecutionContext"):
        if ex_ctx.root_block is None:
            raise ValueError("Root block is not set")
        if self.root_block is None:
            self.root_block = ex_ctx.root_block.model_copy()
        else:
            self.extend_views(ex_ctx.root_block.view_blocks)
        if ex_ctx.output:
            if self.output:
                raise ValueError("Output is already set")
            self.output = ex_ctx.output.model_copy()
            # self.root_block.push(create_view_block(ex_ctx.output, ex_ctx.name + '_output'))
            
    
            
    def add_view(self, view: ViewBlock | HumanMessage | AIMessage | ActionMessage):
        if not isinstance(view, ViewBlock):
            view = create_view_block(view, self.name +"_" + view.role + '_output')
        self.root_block.add(view)
    
    def push_response(self, view: ViewBlock | AIMessage):
        if isinstance(view, AIMessage):
            if self.output is not None:
                raise ValueError("Output is already set")
            self.output = view
            if view.action_calls:
                self.action_calls.extend([a.model_copy() for a in view.action_calls])
        else:
            raise ValueError("Invalid Response view type")
        # self.root_block.add(view)
    
    
    def top_response(self):
        if self.output:
            return True
        return False
    
    def pop_response(self):
        if not self.output:
            raise ValueError("Output is not set")
        response = self.output
        self.root_block.push(create_view_block(self.output, self.name + '_output'))
        self.output = None
        return response