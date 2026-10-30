import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PropertyDef } from "../api/types";
import { defaultsFor, DynamicForm, validateAll } from "./DynamicForm";

afterEach(cleanup);

const def = (p: Partial<PropertyDef>): PropertyDef => ({
  key: "k", label: "K", type: "string", unit: "", required: false, min: null, max: null,
  options: [], default: null, group: "General", help: "", ...p,
});

const schema = [
  def({ key: "power", label: "Power", type: "number", unit: "kW", min: 0, max: 100, required: true, default: 5 }),
  def({ key: "poles", label: "Poles", type: "integer" }),
  def({ key: "drive", label: "Drive", type: "enum", options: ["DOL", "VFD"] }),
  def({ key: "sealed", label: "Sealed", type: "boolean" }),
];

describe("validateAll", () => {
  it("mirrors server rules", () => {
    expect(validateAll(schema, { power: 5 })).toEqual({});
    expect(validateAll(schema, {})).toEqual({ power: "Required" });
    expect(validateAll(schema, { power: 101 }).power).toMatch(/≤ 100/);
    expect(validateAll(schema, { power: 1, poles: 2.5 }).poles).toMatch(/whole/);
    expect(validateAll(schema, { power: 1, drive: "star" }).drive).toBeDefined();
  });
  it("collects defaults", () => {
    expect(defaultsFor(schema)).toEqual({ power: 5 });
  });
});

describe("DynamicForm", () => {
  it("renders one control per definition and emits typed values", () => {
    const onChange = vi.fn();
    render(<DynamicForm schema={schema} values={{ power: 5 }} onChange={onChange} />);
    expect(screen.getByText("kW")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Power/), { target: { value: "12.5" } });
    expect(onChange).toHaveBeenLastCalledWith({ power: 12.5 });
    fireEvent.change(screen.getByLabelText("Drive"), { target: { value: "VFD" } });
    expect(onChange).toHaveBeenLastCalledWith({ power: 5, drive: "VFD" });
    fireEvent.click(screen.getByLabelText("Sealed"));
    expect(onChange).toHaveBeenLastCalledWith({ power: 5, sealed: true });
  });

  it("shows field errors", () => {
    render(<DynamicForm schema={schema} values={{}} onChange={() => {}} errors={{ power: "Required" }} />);
    expect(screen.getByText("Required")).toBeTruthy();
  });
});
