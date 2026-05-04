import React, { useRef, useCallback, useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { getLangFromFilename } from '../../lib/language';

interface CodeEditorProps {
  content: string;
  filename: string;
  isModified?: boolean;
  onChange?: (value: string) => void;
  onSave?: (value: string) => void;
}

function getLang(filename: string): string {
  return getLangFromFilename(filename, 'monaco');
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  content,
  filename,
  isModified,
  onChange,
  onSave,
}) => {
  const editorRef = useRef<any>(null);
  const [hasChanged, setHasChanged] = useState(false);
  const currentValueRef = useRef(content);

  useEffect(() => {
    currentValueRef.current = content;
    setHasChanged(false);
  }, [content, filename]);

  const handleEditorDidMount = useCallback((editor: any) => {
    editorRef.current = editor;
    
    // 绑定 Ctrl+S / Cmd+S 保存快捷键
    editor.addCommand((window as any).monaco?.KeyMod?.CtrlCmd | (window as any).monaco?.KeyCode?.KeyS, () => {
      if (onSave && currentValueRef.current !== undefined) {
        onSave(currentValueRef.current);
        setHasChanged(false);
      }
    });
  }, [onSave]);

  const handleChange = useCallback((value: string | undefined) => {
    if (value === undefined) return;
    currentValueRef.current = value;
    setHasChanged(true);
    onChange?.(value);
  }, [onChange]);

  const showModified = isModified || hasChanged;

  return (
    <div className="h-full flex flex-col bg-gray-950">
      {/* Header */}
      <div className="flex items-center justify-between bg-gray-800 px-3 py-1 text-[10px] text-gray-400 border-b border-gray-700 z-10 shrink-0">
        <div className="flex items-center gap-2">
          <span>{filename}</span>
          {showModified && (
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" title="已修改" />
          )}
        </div>
        <div className="flex items-center gap-2">
          {showModified && (
            <button
              onClick={() => {
                if (onSave && currentValueRef.current !== undefined) {
                  onSave(currentValueRef.current);
                  setHasChanged(false);
                }
              }}
              className="px-2 py-0.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-[10px] transition-colors"
            >
              保存
            </button>
          )}
        </div>
      </div>
      
      {/* Editor */}
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language={getLang(filename)}
          value={content}
          theme="vs-dark"
          onChange={handleChange}
          onMount={handleEditorDidMount}
          options={{
            fontSize: 13,
            fontFamily: 'Consolas, "Courier New", monospace',
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            lineNumbers: 'on',
            tabSize: 4,
            insertSpaces: true,
            wordWrap: 'on',
            renderWhitespace: 'selection',
            folding: true,
            bracketPairColorization: { enabled: true },
            readOnly: false,
          }}
          loading={
            <div className="h-full flex items-center justify-center text-gray-500 text-xs">
              加载编辑器...
            </div>
          }
        />
      </div>
    </div>
  );
};
