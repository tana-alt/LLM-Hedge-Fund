import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fund.common import load, save
from fund.valuation import build_valuation, dcf, historical_bridge, reverse_growth, release_facts
import fund.paper as paper
import fund.experiment as experiment
import fund.audit as audit


class ValuationTests(unittest.TestCase):
    def test_dcf_and_reverse_growth(self):
        base={"revenue":1000,"cash":100,"debt_current":10,"debt_long":20,"shares":10}
        a={"sales_growth":.05,"ebit_margin":.10,"tax_rate":.25,"da_sales":.02,"capex_sales":.03,"nwc_investment_sales":.01,"wacc":.08,"terminal_growth":.02}
        value=dcf(base,a)
        first=value["forecast"][0]
        self.assertAlmostEqual(first["fcff"],1050*(.10*.75+.02-.03-.01))
        self.assertAlmostEqual(value["equity_value"],value["enterprise_value"]+70)
        self.assertAlmostEqual(reverse_growth(base,a,value["per_share"])["sales_growth_implied"],.05,places=7)

    def test_reverse_growth_undefined_for_negative_fcff_margin(self):
        base={"revenue":1000,"cash":100,"debt_current":10,"debt_long":20,"shares":10}
        a={"sales_growth":.05,"ebit_margin":.02,"tax_rate":.25,"da_sales":.01,"capex_sales":.05,"nwc_investment_sales":.01,"wacc":.08,"terminal_growth":.02}
        result=reverse_growth(base,a,100)
        self.assertIsNone(result["sales_growth_implied"])
        self.assertIn("nonpositive",result["undefined_reason"])

    def test_release_fact_units(self):
        raw={"source_url":"https://www.sec.gov/Archives/edgar/data/909832/x","sha256":"abc","filing":{"filed":"2026-09-24"},"text":"FISCAL YEAR 2026 OPERATING RESULTS Total revenue 95,723 86,156 303,154 275,235 Operating income 3,801 3,341 11,685 10,383 Net cash provided by operating activities 15,825 13,335 Additions to property and equipment (6,435) (5,498) Shares used in calculation (000's): Basic 443,975 444,007 443,953 443,985 Diluted 444,364 444,706 444,427 444,803"}
        out=release_facts(raw)
        self.assertEqual(out["revenue"]["value"],303154000000)
        self.assertEqual(out["shares"]["value"],444427000)
        self.assertEqual(out["revenue"]["fiscal_year"],2026)

    def test_audited_year_overrides_same_year_preliminary(self):
        raw={k:{"value":v} for k,v in {"revenue":1000,"cash":100,"debt_current":10,"debt_long":20,"shares":10,"cfo":100,"capex":20,"interest":1,"tax":10,"net_income":30,"operating_income":50}.items()}
        ledger={"fiscal_years":{"2026":raw}}
        prelim={k:{"value":v["value"]*2,"fiscal_year":2026} for k,v in raw.items()}
        bridge=historical_bridge(ledger,prelim)
        self.assertNotIn("2026_preliminary",bridge)
        a={"sales_growth":.05,"ebit_margin":.10,"tax_rate":.25,"da_sales":.02,"capex_sales":.03,"nwc_investment_sales":.01,"wacc":.04,"terminal_growth":-.02}
        v=build_valuation(bridge,{"bear":a,"base":a,"bull":a},100)
        self.assertEqual(v["input_base"]["revenue"],1000)
        self.assertTrue(v["sensitivity"])


class PaperTests(unittest.TestCase):
    def test_fill_cost_dividend_and_benchmarks(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            run=private/"runs"/"2026-09-28"/"result.json"
            save(run,{"status":"decision_frozen","pm_decision":{"action":"BUY","target_weight":.1,"decision_id":"x"},"stages":{"pm_decision":{"risk_cap":.2}}})
            bars={"COST":{"Open":100,"High":105,"Low":99,"Close":104,"Volume":1000,"Dividends":1,"Stock Splits":0},"SPY":{"Open":50,"High":52,"Low":49,"Close":51,"Volume":1000,"Dividends":0,"Stock Splits":0}}
            with patch.object(paper,"PRIVATE",private),patch.object(paper,"_bar",side_effect=lambda symbol,day:bars[symbol]):
                result=paper.close_day("2026-09-28")
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["trade_shares"],100)
            self.assertAlmostEqual(result["one_way_cost"],10)
            self.assertAlmostEqual(result["nav"],100390)
            self.assertEqual(result["cost_buy_hold_proxy"],104000)
            self.assertEqual(result["spy_buy_hold_proxy"],102000)

    def test_missing_decision_still_books_corporate_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            save(private/"paper_account.json",{"cash":90000,"shares":100,"last_day":"2026-09-25","risk_cap":.2,"benchmark_cost_shares":100,"benchmark_cost_cash":0,"benchmark_spy_shares":200,"benchmark_spy_cash":0})
            bars={"COST":{"Open":50,"High":52,"Low":49,"Close":51,"Volume":1000,"Dividends":1,"Stock Splits":2},"SPY":{"Open":50,"High":52,"Low":49,"Close":51,"Volume":1000,"Dividends":.2,"Stock Splits":0}}
            with patch.object(paper,"PRIVATE",private),patch.object(paper,"_bar",side_effect=lambda symbol,day:bars[symbol]):
                result=paper.close_day("2026-09-28")
            self.assertEqual(result["status"],"completed")
            self.assertTrue(result["new_discretionary_trade_suppressed"])
            self.assertEqual(result["trade_shares"],0)
            self.assertEqual(result["shares"],200)
            self.assertEqual(result["cash"],90200)
            self.assertEqual(result["cost_buy_hold_proxy"],10400)
            self.assertEqual(result["spy_buy_hold_proxy"],10240)

    def test_close_catches_up_missed_session_before_today(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            save(private/"paper_account.json",{"cash":100000,"shares":0,"last_day":"2026-09-24","risk_cap":.2,"benchmark_cost_shares":100,"benchmark_cost_cash":0,"benchmark_spy_shares":200,"benchmark_spy_cash":0})
            bars={"COST":{"Open":100,"High":102,"Low":99,"Close":101,"Volume":1000,"Dividends":0,"Stock Splits":0},"SPY":{"Open":50,"High":52,"Low":49,"Close":51,"Volume":1000,"Dividends":0,"Stock Splits":0}}
            with patch.object(paper,"PRIVATE",private),patch.object(paper,"_bar",side_effect=lambda symbol,day:bars[symbol]):
                self.assertEqual(paper.close_day("2026-09-28")["code"],"unprocessed_prior_session")
                result=paper.close_through("2026-09-28")
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["sessions_processed"],["2026-09-25","2026-09-28"])

    def test_first_close_catches_up_first_frozen_run(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            save(private/"runs"/"2026-09-28"/"result.json",{"status":"decision_frozen","pm_decision":{"action":"WATCH","target_weight":0,"decision_id":"first"},"stages":{"pm_decision":{"risk_cap":.2}}})
            bars={"COST":{"Open":100,"High":102,"Low":99,"Close":101,"Volume":1000,"Dividends":0,"Stock Splits":0},"SPY":{"Open":50,"High":52,"Low":49,"Close":51,"Volume":1000,"Dividends":0,"Stock Splits":0}}
            with patch.object(paper,"PRIVATE",private),patch.object(paper,"_bar",side_effect=lambda symbol,day:bars[symbol]):
                result=paper.close_through("2026-09-29")
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["sessions_processed"],["2026-09-28","2026-09-29"])

    def test_orphaned_report_restores_account_without_second_fill(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            after={"cash":90000,"shares":100,"last_day":"2026-09-28"}
            save(private/"runs"/"2026-09-28"/"fill_and_pnl.json",{"status":"completed","day":"2026-09-28","account_after":after,"trade_shares":100})
            with patch.object(paper,"PRIVATE",private),patch.object(paper,"_bar",side_effect=AssertionError("must not refetch")):
                result=paper.close_day("2026-09-28")
            self.assertEqual(result["trade_shares"],100)
            self.assertEqual(load(private/"paper_account.json"),after)


class TimingTests(unittest.TestCase):
    def test_non_draft_cannot_freeze_past_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(experiment,"PRIVATE",Path(temp)):
                result=experiment.run_research("2020-01-02")
            self.assertEqual(result["status"],"late_not_frozen")


class CycleAuditTests(unittest.TestCase):
    def test_classifies_model_failure_separately_from_working_operations_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            folder=private/"runs"/"2026-09-28"
            save(folder/"result.json",{"status":"decision_frozen","research_level":"L3","pm_decision":{"decision_id":"abc"},"stages":{"data":{"status":"passed"},"shadow_alert":{"status":"failed","failure_class":"llm_reasoning","code":"shadow_quote"}}})
            save(folder/"fill_and_pnl.json",{"status":"completed","nav":100000})
            save(folder/"review.json",{"status":"completed","review":{"gate":"pass","verified_defects":[]}})
            with patch.object(audit,"PRIVATE",private):
                result=audit.audit_day("2026-09-28")
            self.assertTrue(result["operations_loop_ran"])
            self.assertEqual(result["llm_failures"][0]["code"],"shadow_quote")
            self.assertEqual(result["system_failures"],[])
            self.assertEqual(result["status"],"failed")

    def test_records_provider_and_price_failures_by_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)
            folder=private/"runs"/"2026-09-28"
            save(folder/"result.json",{"status":"decision_frozen","research_level":"L3","pm_decision":{"decision_id":"abc"},"stages":{"data":{"status":"passed"}}})
            save(folder/"review.json",{"status":"failed","failure_class":"system_runtime","code":"modelctl_exit"})
            save(folder/"paper_failure.json",{"status":"failed","failure_class":"system_data","code":"market_bar_unavailable"})
            with patch.object(audit,"PRIVATE",private):
                result=audit.audit_day("2026-09-28")
            self.assertEqual({x["code"] for x in result["system_failures"]},{"modelctl_exit","market_bar_unavailable"})
            self.assertFalse(result["operations_loop_ran"])


if __name__=="__main__":unittest.main()
