from decimal import Decimal

amounts = [Decimal(value) for value in input_data["amounts"]]
result = {"total": str(sum(amounts)), "count": len(amounts)}
