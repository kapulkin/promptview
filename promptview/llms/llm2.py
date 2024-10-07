from typing import Dict, List, Type

from promptview.llms.clients.base import BaseLlmClient
from promptview.llms.exceptions import LLMToolNotFound
from promptview.llms.interpreter import LlmInterpreter
from promptview.llms.llm import ToolChoice
from promptview.llms.messages import BaseMessage, HumanMessage
from promptview.llms.tracer import Tracer
from promptview.llms.utils.action_manager import Actions
from promptview.prompt.execution_context import LlmExecutionContext
from promptview.prompt.mvc import ViewBlock
from pydantic import BaseModel, ValidationError


class LLM(BaseModel, LlmInterpreter):
    model: str
    name: str
    temperature: float | None = None
    max_tokens: int | None = None
    stop_sequences: List[str] | None = None
    logit_bias: Dict[str, int] | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    logprobs: bool | None = None
    seed: int | None = None
    frequency_penalty: float | None = None
    is_traceable: bool | None = True
    client: BaseLlmClient
    # client: Union[OpenAiLlmClient, PhiLlmClient, AzureOpenAiLlmClient]    
    parallel_tool_calls: bool = True 
    
    class Config:
        arbitrary_types_allowed = True   
        
    def get_llm_args(self, actions=None, **kwargs):
        model_kwargs={}
        stop_sequences = kwargs.get("stop_sequences", self.stop_sequences)
        if stop_sequences:
            model_kwargs['stop'] = stop_sequences
        logit_bias = kwargs.get("logit_bias", self.logit_bias)
        if logit_bias:            
            model_kwargs['logit_bias'] = logit_bias
        top_p = kwargs.get("top_p", self.top_p)
        if top_p:
            if top_p > 1.0 or top_p < 0.0:
                raise ValueError("top_p must be between 0.0 and 1.0")
            model_kwargs['top_p'] = top_p
        presence_penalty = kwargs.get("presence_penalty", self.presence_penalty)
        if presence_penalty:
            if presence_penalty > 2.0 or presence_penalty < -2.0:
                raise ValueError("presence_penalty must be between -2.0 and 2.0")
            model_kwargs['presence_penalty'] = presence_penalty
        frequency_penalty = kwargs.get("frequency_penalty", self.frequency_penalty)
        if frequency_penalty:
            if frequency_penalty > 2.0 or frequency_penalty < -2.0:
                raise ValueError("frequency_penalty must be between -2.0 and 2.0")
            model_kwargs['frequency_penalty'] = frequency_penalty
        temperature = kwargs.get("temperature", self.temperature)
        if temperature is not None:
            model_kwargs['temperature'] = temperature
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens is not None:
            model_kwargs['max_tokens'] = max_tokens

        model = kwargs.get("model", self.model)
        if model is not None:
            model_kwargs['model'] = model        
        
        seed = kwargs.get("seed", self.seed)
        if seed is not None:
            model_kwargs['seed'] = seed
            
        parallel_tool_calls = kwargs.get("parallel_tool_calls", self.parallel_tool_calls)
        if parallel_tool_calls is not None and actions:
            model_kwargs['parallel_tool_calls'] = parallel_tool_calls
            
        logprobs = kwargs.get("logprobs", self.logprobs)
        if logprobs is not None:
            model_kwargs['logprobs'] = logprobs        
        return model_kwargs
    
    
    
    
    async def complete(
        self,
        # view_block: ViewBlock,
        messages: List[BaseMessage],
        actions: Actions | List[type[BaseModel]] | None = None,
        tool_choice: ToolChoice | BaseModel | None = None,
        tracer_run=None,
        metadata={},
        **kwargs,
    ):
        # messages, actions = self.transform(
        #         root_block=view_block, 
        #         actions=actions, 
        #         **kwargs
        #     )        
        llm_kwargs = self.get_llm_args(tools=actions, **kwargs)
        with Tracer(
            is_traceable=self.is_traceable,
            tracer_run=tracer_run,
            run_type="llm",
            name=self.name,
            inputs={"messages": [msg.to_openai() for msg in messages]},
            metadata=metadata,
        ) as llm_run:
            try:
                response = await self.client.complete(
                        messages, 
                        actions=actions,
                        tool_choice=tool_choice,
                        run_id=str(llm_run.id),
                        **llm_kwargs
                    )
                llm_run.end(outputs=response.raw)
                return response  
            except Exception as e:
                llm_run.end(errors=str(e))
                raise e
    
    
    async def stream(
        self,
        # view_block: ViewBlock,
        messages: List[BaseMessage],
        actions: Actions | List[type[BaseModel]] | None = None,
        tool_choice: ToolChoice | BaseModel | None = None,
        tracer_run=None,
        metadata={},
        **kwargs,
    ):
        # messages, actions = self.transform(
        #         root_block=view_block, 
        #         actions=actions, 
        #         **kwargs
        #     )
        llm_kwargs = self.get_llm_args(tools=actions, **kwargs)
        metadata["model"] = llm_kwargs.get("model", self.model)
        with Tracer(
            is_traceable=self.is_traceable,
            tracer_run=tracer_run,
            run_type="llm",
            name=self.name,
            inputs={"messages": [msg.to_openai() for msg in messages]},
            metadata=metadata,
        ) as llm_run:
            try:
                async for chunk in self.client.stream(
                    messages, 
                    actions=actions,
                    tool_choice=tool_choice,
                    run_id=str(llm_run.id),
                    **llm_kwargs
                ):
                    if not chunk.did_finish:
                        yield chunk
                llm_run.end(outputs={"message": chunk.full_response})
                yield chunk
                return
            except Exception as e:
                llm_run.end(errors=str(e))
                raise e
    
    