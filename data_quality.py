"""CLI and compatibility wrapper for quant.data.quality."""

from quant.data.quality import DataQualityChecker, batch_process_stocks

__all__ = ["DataQualityChecker", "batch_process_stocks"]


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    checker = DataQualityChecker(data_dir="data")

    test_symbols = ["000001", "000002", "002594"]
    for symbol in test_symbols:
        try:
            report = checker.generate_quality_report(symbol)
            logging.info("Quality report for %s: %s", symbol, report)
        except Exception as exc:
            logging.error("Report for %s failed: %s", symbol, exc)
