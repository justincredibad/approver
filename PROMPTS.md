# Design prompts

These are the original prompts that define the scope of this project, copied
verbatim as the design spec for the credit-scoring agent.

## Prompt 1

> you are a credit approver working in a bank, responsible for assessing credit worthiness of customers.
> there are a list of product assessment rules for asset classes such as hire purchase loans. a sample of these rules are. dsr(debt servicing ratio) must be within 60%, 80% if annual income exceeds 72000.
> LTV must be 70% of total purchase price of vehicle or valuation of vehicle, whichever is lower. If the OMV is less than 20000. if OMV is above 20000, LTV must be lower than 60%.
> you are to grade the creditworthiness of the customer from 1 to 100 based on these criterias.
> age
> relationship status
> employment sector
> existence of ACRA litigations
> CBES (credit bureau) records. CBES states the punctuality of payments (secured and unsecured loans) and displays the balance of them so that you can estimate DSR well.
> the agent should also be able to estimate the valuation of the loan collateral (in this example, value of car sold in singapore based on sgcarmart, carros).
> i want a GUI where i get to enter a candidate 's
> age
> gender
> relationship status
> employment sector
> employment annual income
> existence of ACRA litigations
> CBES (credit bureau) records
> usually, loan applications can involve MyInfo, where CPF contributions can verify employment status and do KYC as well.
> once the agent has these information, it should return a number from 1 to 100, if the score is above 80,the loan can be automatically approved.
> i want this agent to be hosted on github.

## Prompt 2

> vehicle valuation can be done using selenium to search the car make and model, and year of manufacturing, and COE expiry date, cars in singapore expire when its COE is due
