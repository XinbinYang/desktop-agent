import React, { useRef, useCallback, useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { useTheme } from '../../hooks/useTheme';
import { getLangFromFilename } from '../../lib/language';
import { ensureMonacoTheme, ensureMonacoThemes, getMonacoThemeName } from '../../lib/monacoTheme';

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
  const monacoRef = useRef<any>(null);
  const [hasChanged, setHasChanged] = useState(false);
  const currentValueRef = useRef(content);
  const { resolved } = useTheme();
  const monacoTheme = getMonacoThemeName(resolved);

  useEffect(() => {
    currentValueRef.current = content;
    setHasChanged(false);
  }, [content, filename]);

  useEffect(() => {
    if (monacoRef.current) {
      ensureMonacoTheme(monacoRef.current, resolved);
    }
  }, [resolved]);

  const handleEditorWillMount = useCallback((monaco: any) => {
    monacoRef.current = monaco;
    ensureMonacoThemes(monaco);
  }, []);

  const handleEditorDidMount = useCallback((editor: any, monaco: any) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    ensureMonacoThemes(monaco);

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      if (onSave && currentValueRef.current !== undefined) {
        onSave(currentValueRef.current);
        setHasChanged(false);
      }
    });
  }, [onSave, resolved]);

  const handleChange = useCallback((value: string | undefined) => {
    if (value === undefined) return;
    currentValueRef.current = value;
    setHasChanged(true);
    onChange?.(value);
  }, [onChange]);

  const showModified = isModified || hasChanged;

  return (
    <div className="h-full flex flex-col bg-app">
      <div className="flex items-center justify-between bg-surface px-3 py-1 text-[10px] text-fg-secondary border-b border-border z-10 shrink-0">
        <div className="flex items-center gap-2">
          <span>{filename}</span>
          {showModified && (
            <span className="w-1.5 h-1.5 rounded-full bg-accent" title="已修改" />
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
              className="px-2 py-0.5 bg-accent/85 hover:bg-accent text-fg-on-accent rounded text-[10px] transition-colors"
            >
              保存
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language={getLang(filename)}
          value={content}
          theme={monacoTheme}
          onChange={handleChange}
          beforeMount={handleEditorWillMount}
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
            <div className="h-full flex items-center justify-center text-fg-muted text-xs">
              加载编辑器...
            </div>
          }
        />
      </div>
    </div>
  );
};
