type LanguagePlatform = 'monaco' | 'syntax-highlighter' | 'generic';

const BASE_MAP: Record<string, string> = {
  py: 'python', js: 'javascript', ts: 'typescript',
  css: 'css', scss: 'scss', html: 'html', md: 'markdown',
  json: 'json', yaml: 'yaml', yml: 'yaml',
  rs: 'rust', go: 'go', java: 'java', cpp: 'cpp',
  c: 'c', cs: 'csharp', php: 'php', rb: 'ruby',
  swift: 'swift', kt: 'kotlin', sql: 'sql',
  vue: 'vue', svelte: 'svelte', xml: 'xml', ini: 'ini',
};

const PLATFORM_OVERRIDES: Record<LanguagePlatform, Record<string, string>> = {
  'monaco': {
    jsx: 'javascript', tsx: 'typescript',
    sh: 'shell', bash: 'shell',
    dockerfile: 'dockerfile', toml: 'ini',
  },
  'syntax-highlighter': {
    jsx: 'jsx', tsx: 'tsx',
    sh: 'bash', bash: 'bash',
    dockerfile: 'dockerfile', toml: 'toml',
  },
  'generic': {
    jsx: 'jsx', tsx: 'tsx',
    sh: 'bash', bash: 'bash',
    dockerfile: 'docker', toml: 'toml',
  },
};

const PLATFORM_FALLBACKS: Record<LanguagePlatform, string> = {
  'monaco': 'plaintext',
  'syntax-highlighter': 'text',
  'generic': 'text',
};

export function getLangFromFilename(filename: string, platform: LanguagePlatform = 'generic'): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const overrides = PLATFORM_OVERRIDES[platform] || {};
  return overrides[ext] || BASE_MAP[ext] || PLATFORM_FALLBACKS[platform];
}
