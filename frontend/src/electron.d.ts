export {};

interface CaptureRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

declare global {
  interface Window {
    electronAPI?: {
      selectFolder: () => Promise<string | null>;
      selectFile: () => Promise<string | null>;
      getAppVersion: () => Promise<string>;
      getAuthToken: () => Promise<string | null>;
      captureRegion: (rect: CaptureRect) => Promise<string | null>;
      onNewSession: (cb: () => void) => () => void;
    };
  }
}
