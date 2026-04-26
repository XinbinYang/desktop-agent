export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  vision: boolean;
  context: number;
}

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result: string;
  timestamp: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  imageBase64?: string;
  isTool: boolean;
  reasoning?: string;
}

export interface WS_EVENT {
  type: 'content' | 'reasoning' | 'tool_call' | 'image' | 'status' | 'error' | 'done' | 'cleared' | 'interrupted' | 'tool_result';
  data: any;
}