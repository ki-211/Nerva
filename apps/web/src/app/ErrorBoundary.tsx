import { Component, type ErrorInfo, type ReactNode } from 'react';
import { clientLogger } from '../lib/clientLogger';
import { createClientErrorId } from '../lib/errors';

type Props = { children: ReactNode };
type State = { failed: boolean; errorId: string };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, errorId: '' };

  static getDerivedStateFromError(): State {
    return { failed: true, errorId: createClientErrorId() };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    clientLogger.error('react_render_failed', error, {
      operation: 'react.render', requestId: this.state.errorId, componentStack: info.componentStack,
    });
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <main className="fatal-error" role="alert">
          <h1>页面加载失败</h1>
          <p>操作失败，请稍后重试。错误编号：{this.state.errorId}。若问题持续，请导出诊断日志并联系管理员。</p>
          <button type="button" onClick={() => window.location.reload()}>重新加载</button>
        </main>
      );
    }
    return this.props.children;
  }
}
