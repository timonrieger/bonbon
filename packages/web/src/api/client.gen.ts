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
export type ReceiptSummary = {
    id: string;
    status: Status;
    store: string | null;
    purchase_date: string | null;
    total_rappen: number | null;
    uploaded_by_name: string | null;
    created_at: string;
};
export type ReceiptList = {
    receipts: ReceiptSummary[];
};
export type ReceiptItem = {
    position: number;
    name: string;
    quantity: number;
    unit_price_rappen: number | null;
    amount_rappen: number;
    category: string;
};
export type ReceiptDetail = {
    id: string;
    status: Status;
    store: string | null;
    purchase_date: string | null;
    total_rappen: number | null;
    uploaded_by_name: string | null;
    created_at: string;
    image_url: string;
    items: ReceiptItem[];
};
export type CategoryTotal = {
    category: string;
    total_rappen: number;
};
export type StoreTotal = {
    store: string | null;
    total_rappen: number;
};
export type MonthlyReport = {
    month: string;
    total_rappen: number;
    receipt_count: number;
    previous_month_total_rappen: number;
    by_category: CategoryTotal[];
    by_store: StoreTotal[];
};
export type MonthTotal = {
    month: string;
    total_rappen: number;
};
export type SpendingTrend = {
    months: MonthTotal[];
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
 * GET /households/{household_id}/receipts
 */
export function listReceipts({ householdId, month }: {
    householdId: string;
    month?: string | null;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: ReceiptList;
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts${QS.query(QS.explode({
        month
    }))}`, {
        ...opts
    }));
}
/**
 * GET /households/{household_id}/receipts/{receipt_id}
 */
export function getReceipt({ householdId, receiptId }: {
    householdId: string;
    receiptId: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: ReceiptDetail;
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/receipts/${encodeURIComponent(receiptId)}`, {
        ...opts
    }));
}
/**
 * GET /households/{household_id}/reports/monthly
 */
export function getMonthlyReport({ householdId, month }: {
    householdId: string;
    month: string;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: MonthlyReport;
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/reports/monthly${QS.query(QS.explode({
        month
    }))}`, {
        ...opts
    }));
}
/**
 * GET /households/{household_id}/reports/trend
 */
export function getSpendingTrend({ householdId, months }: {
    householdId: string;
    months?: number;
}, opts?: Oazapfts.RequestOpts) {
    return oazapfts.ok(oazapfts.fetchJson<{
        status: 200;
        data: SpendingTrend;
    } | {
        status: 422;
        data: HttpValidationError;
    }>(`/households/${encodeURIComponent(householdId)}/reports/trend${QS.query(QS.explode({
        months
    }))}`, {
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
export enum Status {
    Uploaded = "uploaded",
    Processing = "processing",
    Done = "done",
    Failed = "failed",
    Duplicate = "duplicate"
}
