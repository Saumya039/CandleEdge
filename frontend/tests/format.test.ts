import { describe, expect, it } from "vitest";
import { countdown, dirLabel, istHM, istTime, num, pct, rupees } from "@/lib/format";

describe("format", () => {
  it("renders every time in Asia/Kolkata regardless of the machine zone", () => {
    expect(istTime("2026-10-23T03:45:00Z")).toBe("09:15:00");
    expect(istHM(Date.UTC(2026, 9, 23, 10, 0, 0) / 1000)).toBe("15:30");
    expect(istTime(null)).toBe("—");
    expect(istTime("garbage")).toBe("—");
  });
  it("never turns missing data into a number", () => {
    expect(num(null)).toBe("Unavailable");
    expect(num(undefined)).toBe("Unavailable");
    expect(num(Number.NaN)).toBe("Unavailable");
    expect(rupees(null)).toBe("Unavailable");
    expect(pct(null)).toBe("Unavailable");
  });
  it("formats numbers Indian-style", () => {
    expect(num(24512.349)).toBe("24,512.35");
    expect(rupees(-125000)).toBe("-₹1,25,000");
    expect(pct(0.456)).toBe("+0.46%");
  });
  it("formats countdowns and labels", () => {
    expect(countdown(3725)).toBe("1h 2m 05s");
    expect(countdown(-5)).toBe("0m 00s");
    expect(dirLabel("BUY_CALL")).toBe("BUY CALL");
  });
});
