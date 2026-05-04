import React from 'react';
import { Light as SyntaxHighlighter } from 'react-syntax-highlighter';
import { atomOneDark } from 'react-syntax-highlighter/dist/esm/styles/hljs';
import { getLangFromFilename } from '../../lib/language';

// 手动注册语言，避免 ESM 动态加载问题
import python from 'react-syntax-highlighter/dist/esm/languages/hljs/python';
import javascript from 'react-syntax-highlighter/dist/esm/languages/hljs/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/hljs/typescript';
import tsx from 'react-syntax-highlighter/dist/esm/languages/hljs/typescript';
import jsx from 'react-syntax-highlighter/dist/esm/languages/hljs/javascript';
import css from 'react-syntax-highlighter/dist/esm/languages/hljs/css';
import scss from 'react-syntax-highlighter/dist/esm/languages/hljs/scss';
import xml from 'react-syntax-highlighter/dist/esm/languages/hljs/xml';
import markdown from 'react-syntax-highlighter/dist/esm/languages/hljs/markdown';
import json from 'react-syntax-highlighter/dist/esm/languages/hljs/json';
import yaml from 'react-syntax-highlighter/dist/esm/languages/hljs/yaml';
import bash from 'react-syntax-highlighter/dist/esm/languages/hljs/bash';
import rust from 'react-syntax-highlighter/dist/esm/languages/hljs/rust';
import go from 'react-syntax-highlighter/dist/esm/languages/hljs/go';
import java from 'react-syntax-highlighter/dist/esm/languages/hljs/java';
import cpp from 'react-syntax-highlighter/dist/esm/languages/hljs/cpp';
import c from 'react-syntax-highlighter/dist/esm/languages/hljs/c';
import csharp from 'react-syntax-highlighter/dist/esm/languages/hljs/csharp';
import php from 'react-syntax-highlighter/dist/esm/languages/hljs/php';
import ruby from 'react-syntax-highlighter/dist/esm/languages/hljs/ruby';
import swift from 'react-syntax-highlighter/dist/esm/languages/hljs/swift';
import kotlin from 'react-syntax-highlighter/dist/esm/languages/hljs/kotlin';
import sql from 'react-syntax-highlighter/dist/esm/languages/hljs/sql';
import dockerfile from 'react-syntax-highlighter/dist/esm/languages/hljs/dockerfile';
import ini from 'react-syntax-highlighter/dist/esm/languages/hljs/ini';
import toml from 'react-syntax-highlighter/dist/esm/languages/hljs/ini';

SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('tsx', tsx);
SyntaxHighlighter.registerLanguage('jsx', jsx);
SyntaxHighlighter.registerLanguage('css', css);
SyntaxHighlighter.registerLanguage('scss', scss);
SyntaxHighlighter.registerLanguage('html', xml);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('rust', rust);
SyntaxHighlighter.registerLanguage('go', go);
SyntaxHighlighter.registerLanguage('java', java);
SyntaxHighlighter.registerLanguage('cpp', cpp);
SyntaxHighlighter.registerLanguage('c', c);
SyntaxHighlighter.registerLanguage('csharp', csharp);
SyntaxHighlighter.registerLanguage('php', php);
SyntaxHighlighter.registerLanguage('ruby', ruby);
SyntaxHighlighter.registerLanguage('swift', swift);
SyntaxHighlighter.registerLanguage('kotlin', kotlin);
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('docker', dockerfile);
SyntaxHighlighter.registerLanguage('dockerfile', dockerfile);
SyntaxHighlighter.registerLanguage('vue', xml);
SyntaxHighlighter.registerLanguage('svelte', xml);
SyntaxHighlighter.registerLanguage('xml', xml);
SyntaxHighlighter.registerLanguage('ini', ini);
SyntaxHighlighter.registerLanguage('toml', toml);

interface CodeViewerProps {
  content: string;
  filename: string;
}

function getLang(filename: string): string {
  return getLangFromFilename(filename, 'syntax-highlighter');
}

export const CodeViewer: React.FC<CodeViewerProps> = ({ content, filename }) => {
  if (!content) {
    return (
      <div className="h-full overflow-auto bg-gray-950">
        <div className="sticky top-0 bg-gray-800 px-3 py-1 text-[10px] text-gray-400 border-b border-gray-700 z-10">
          {filename}
        </div>
        <div className="p-4 text-sm text-gray-500">文件内容为空</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-gray-950">
      <div className="sticky top-0 bg-gray-800 px-3 py-1 text-[10px] text-gray-400 border-b border-gray-700 z-10">
        {filename}
      </div>
      <SyntaxHighlighter
        language={getLang(filename)}
        style={atomOneDark}
        customStyle={{ margin: 0, padding: '12px 16px', fontSize: '12px', background: 'transparent' }}
        showLineNumbers
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
};
