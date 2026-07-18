import { describe, expect, it } from "vitest";

import AppErrorBoundary from "./AppErrorBoundary";

describe("AppErrorBoundary", () => {
  it("renders children while the app is healthy", () => {
    const boundary = new AppErrorBoundary({ children: "healthy-app" });
    boundary.state = { error: null };
    expect(boundary.render()).toBe("healthy-app");
  });

  it("renders a visible recovery screen after a render failure", () => {
    const error = new Error("測試畫面錯誤");
    const boundary = new AppErrorBoundary({ children: "healthy-app" });
    boundary.state = AppErrorBoundary.getDerivedStateFromError(error);
    const recovery = boundary.render();

    expect(recovery.props.className).toBe("app-error-screen");
    expect(recovery.props.role).toBe("alert");
  });
});
