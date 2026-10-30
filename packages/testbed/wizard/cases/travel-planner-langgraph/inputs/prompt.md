# Travel planner

## Product and users

The travel planner helps travellers prepare and revise a trip itinerary through a conversation. A traveller can state a destination, travel dates, budget, and preferences. The assistant asks for missing information that it needs to plan the trip.

## Functions and workflow

The system identifies the travel request, researches available options, and prepares an itinerary. It can search for flights and hotels, check the weather, read travel advisories, and calculate whether the proposed trip fits the budget. It uses a clarification step when the request needs more information.

The traveller can change the request in later messages. The assistant uses the conversation to keep the trip requirements current and revise the itinerary.

## Product constraints

The stated budget is a limit on the trip cost. The cost calculation includes flights, the full hotel stay, and other costs. The system has a validate_budget tool for checking the total. If available options exceed the budget, the assistant explains this and asks the traveller to decide what to change.

Travel details come from the available travel tools. When a tool does not supply a requested detail, the assistant explains what information is missing. It distinguishes estimates from confirmed tool information.

## Available environment

The example uses LangGraph to coordinate request interpretation, research, clarification, and itinerary preparation. Its travel tools use a fixed sample dataset. The dataset may not contain options for the requested destination. The available functions are search_flights, search_hotels, check_weather, check_travel_advisories, and validate_budget.
