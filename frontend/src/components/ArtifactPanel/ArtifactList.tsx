import React from 'react';
import {
  Globe, Image, Table, Code, Terminal, Video, FileText, Trash2, X
} from 'lucide-react';
import { ArtifactItem, ArtifactType } from '../../types';

const TYPE_ICONS: Record<ArtifactType, React.ElementType> = {
  web: Globe,
  image: Image,
  data: Table,
  code: Code,
  terminal: Terminal,
  video: Video,
};

const TYPE_LABELS: Record<ArtifactType, string> = {
  web: '网页',
  image: '图片',
  data: '数据',
  code: '代码',
  terminal: '终端',
  video: '视频',
};

interface ArtifactListProps {
  artifacts: ArtifactItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onClear: () => void;
}

export const ArtifactList: React.FC<ArtifactListProps> = ({
  artifacts,
  activeId,
  onSelect,
  onDelete,
  onClear,
}) => {
  if (artifacts.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-500 px-4">
        <FileText className="w-8 h-8 mb-2 opacity-50" />
        <div className="text-xs text-center">暂无成果</div>
        <div className="text-[10px] text-center mt-1">Agent 执行文件操作或脚本后，产物将显示在这里</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
        <span className="text-xs font-medium text-gray-300">成果列表 ({artifacts.length})</span>
        <button
          onClick={onClear}
          className="text-[10px] text-gray-500 hover:text-red-400 transition-colors"
          title="清空全部"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {artifacts.map((item) => {
          const Icon = TYPE_ICONS[item.type];
          const isActive = item.id === activeId;
          return (
            <div
              key={item.id}
              className={`group flex items-center gap-2 px-3 py-2 cursor-pointer border-b border-gray-800 transition-colors ${
                isActive ? 'bg-gray-700/60' : 'hover:bg-gray-800/60'
              }`}
              onClick={() => onSelect(item.id)}
            >
              <Icon className={`w-3.5 h-3.5 shrink-0 ${isActive ? 'text-accent' : 'text-gray-500'}`} />
              <div className="flex-1 min-w-0">
                <div className={`text-xs truncate ${isActive ? 'text-white' : 'text-gray-300'}`}>
                  {item.title}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] px-1 rounded bg-gray-800 text-gray-500">
                    {TYPE_LABELS[item.type]}
                  </span>
                  <span className="text-[10px] text-gray-600">
                    {new Date(item.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(item.id); }}
                className="opacity-0 group-hover:opacity-100 p-1 text-gray-500 hover:text-red-400 transition-opacity"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};
