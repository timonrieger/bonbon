/**
 * Bonbon API
 * 0.1.0
 * DO NOT MODIFY - This file has been generated using oazapfts.
 * See https://www.npmjs.com/package/oazapfts
 */
import * as Oazapfts from "@oazapfts/runtime";
import * as QS from "@oazapfts/runtime/query";
export const defaults: Oazapfts.Defaults<Oazapfts.CustomHeaders> = {
    headers: {},
    baseUrl: "/"
};
const oazapfts = Oazapfts.runtime(defaults);
export const servers = {
    server1: "/"
};
export type Household = {
    id: string;
    name: string;
    created_at: string;
    my_role: MyRole;
};
export type ValidationError = {
    loc: (string | number)[];
    "type": string;
};
export type HttpValidationError = {
    detail?: ValidationError[];
};
export type CreateHouseholdRequest = {
    name: string;
};
/**
 * GET /households/{household_id}
 */
export function getHousehold({ householdId }: {
    householdId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: Household;
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}`, {
        ...opts
    }));
}
/**
 * POST /households
 */
export function createHousehold({ createHouseholdRequest }: {
    createHouseholdRequest: CreateHouseholdRequest;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: Household;
    } | {
        status: 422;
        data: HttpValidationError;
    }>("/households", oazapfts.json({
        ...opts,
        method: "POST",
        body: createHouseholdRequest
    })));
}
export enum MyRole {
    Owner = "owner",
    Member = "member"
}
