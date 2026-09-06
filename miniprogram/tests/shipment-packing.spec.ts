import { expect, it } from "vitest";
import type { DraftBoxWrite } from "../api/shipments";
import { copyToFollowingBoxes } from "../modules/shipment-packing";

it("copies a mixed packing method to 32 following boxes without sharing item objects", () => {
  const boxes: DraftBoxWrite[] = Array.from({length:33}, (_,i) => ({boxNo:i+1,groupKey:null,items:[]}));
  boxes[0].items = [{assignmentId:7,quantity:10},{assignmentId:8,quantity:2}];
  const copied = copyToFollowingBoxes(boxes,0,32,"group-1");
  expect(copied).toHaveLength(33);
  expect(copied[32]).toEqual({boxNo:33,groupKey:"group-1",items:[{assignmentId:7,quantity:10},{assignmentId:8,quantity:2}]});
  expect(copied[0].groupKey).toBe("group-1");
  copied[1].items[0].quantity = 3;
  expect(copied[0].items[0].quantity).toBe(10);
  expect(copied[2].items[0].quantity).toBe(10);
  expect(boxes[1].items).toEqual([]);
});

it.each([0,-1,1.5,NaN,Infinity,3])("rejects invalid range %s without changing any box", count => {
  const boxes: DraftBoxWrite[] = [{boxNo:1,groupKey:null,items:[{assignmentId:7,quantity:10}]},{boxNo:2,groupKey:null,items:[]}];
  const before = structuredClone(boxes);
  expect(() => copyToFollowingBoxes(boxes,0,count,"g")).toThrow();
  expect(boxes).toEqual(before);
});

it("rejects the entire copy when a later target is occupied or box numbers are duplicated", () => {
  const boxes: DraftBoxWrite[] = [{boxNo:1,groupKey:null,items:[{assignmentId:7,quantity:10}]},
    {boxNo:2,groupKey:null,items:[]},{boxNo:3,groupKey:null,items:[{assignmentId:8,quantity:1}]}];
  const before = structuredClone(boxes);
  expect(() => copyToFollowingBoxes(boxes,0,2,"g")).toThrow();
  expect(boxes).toEqual(before);
  boxes[2] = {boxNo:2,groupKey:null,items:[]};
  expect(() => copyToFollowingBoxes(boxes,0,1,"g")).toThrow();
});

it("rejects an empty source and invalid item quantities", () => {
  const boxes: DraftBoxWrite[] = [{boxNo:1,groupKey:null,items:[]},{boxNo:2,groupKey:null,items:[]}];
  expect(() => copyToFollowingBoxes(boxes,0,1,"g")).toThrow();
  boxes[0].items=[{assignmentId:7,quantity:0}];
  expect(() => copyToFollowingBoxes(boxes,0,1,"g")).toThrow();
});
