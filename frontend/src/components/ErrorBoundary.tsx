import React, { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="h-screen flex items-center justify-center bg-gray-900 text-gray-100">
          <div className="text-center">
            <h2 className="text-xl font-bold mb-2 text-red-400">出错了</h2>
            <p className="text-sm text-gray-400 mb-4">
              {this.state.error?.message || '未知错误'}
            </p>
            <button
              onClick={() => this.setState({ hasError: false })}
              className="px-4 py-2 bg-agent-600 hover:bg-agent-500 text-white rounded-lg text-sm"
            >
              重试
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
