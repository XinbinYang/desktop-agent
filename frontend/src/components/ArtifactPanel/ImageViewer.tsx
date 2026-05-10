import React from 'react';

interface ImageViewerProps {
  url?: string;
  base64?: string;
}

export const ImageViewer: React.FC<ImageViewerProps> = ({ url, base64 }) => {
  const src = base64 ? `data:image/png;base64,${base64}` : url;
  if (!src) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        无图片数据
      </div>
    );
  }

  return (
    <div className="h-full flex items-center justify-center bg-gray-950 p-4 overflow-auto">
      <img
        src={src}
        alt="preview"
        className="max-w-full max-h-full object-contain rounded shadow-lg"
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />
    </div>
  );
};
