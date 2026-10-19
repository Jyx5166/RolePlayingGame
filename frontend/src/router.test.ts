import { describe, expect, it } from "vitest";

import { appRoutePath, isSafeReturnPath, parseAppRoute } from "./router";

describe("app router", () => {
  it("parses public and private resource routes", () => {
    expect(parseAppRoute("/login")).toEqual({ name: "login" });
    expect(parseAppRoute("/register")).toEqual({ name: "register" });
    expect(parseAppRoute("/cases")).toEqual({ name: "case-list" });
    expect(parseAppRoute("/cases/new")).toEqual({ name: "case-create" });
    expect(parseAppRoute("/cases/42")).toEqual({ name: "case-detail", gameId: 42 });
    expect(parseAppRoute("/play")).toEqual({ name: "script-library" });
    expect(parseAppRoute("/scripts/new")).toEqual({ name: "script-create" });
    expect(parseAppRoute("/personal-center")).toEqual({ name: "personal-center" });
    expect(parseAppRoute("/games/42/prepare")).toEqual({ name: "game-prepare", gameId: 42 });
    expect(parseAppRoute("/games/42")).toEqual({ name: "game-detail", gameId: 42 });
  });

  it("rejects malformed and unrelated paths", () => {
    expect(parseAppRoute("/cases/0")).toEqual({ name: "not-found" });
    expect(parseAppRoute("/cases/1/records")).toEqual({ name: "not-found" });
    expect(isSafeReturnPath("//example.com")).toBe(false);
    expect(isSafeReturnPath("/register")).toBe(false);
    expect(isSafeReturnPath("/games/42/prepare")).toBe(true);
    expect(isSafeReturnPath("/personal-center")).toBe(true);
    expect(isSafeReturnPath("/games/0/prepare")).toBe(false);
  });

  it("builds canonical paths", () => {
    expect(appRoutePath({ name: "case-detail", gameId: 7 })).toBe("/cases/7");
    expect(appRoutePath({ name: "case-create" })).toBe("/cases/new");
    expect(appRoutePath({ name: "personal-center" })).toBe("/personal-center");
  });
});
