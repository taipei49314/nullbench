import { Component } from "react";
import { CircleAlert, RefreshCw } from "lucide-react";

export default class AppErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("LOTTO//LAB render failure", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="app-error-screen" role="alert">
        <CircleAlert size={42} />
        <strong>戰情室顯示發生錯誤</strong>
        <p>{this.state.error.message || "未知的畫面錯誤"}</p>
        <button type="button" onClick={() => window.location.reload()}>
          <RefreshCw size={17} />
          重新載入戰情室
        </button>
      </main>
    );
  }
}
