#!/bin/bash
# Test runner script

# Set colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Running test suite for Redis Salesforce/Observe Integration${NC}"
echo "========================================================"

# Create test output directory if it doesn't exist
mkdir -p test_output

# Ensure we're in the project root directory
cd "$(dirname "$0")"

# Run Salesforce tests
echo -e "${YELLOW}Running Salesforce Tests...${NC}"
python tests/test_salesforce.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Salesforce Tests Passed${NC}"
else
    echo -e "${RED}Salesforce Tests Failed${NC}"
fi
echo "========================================================"

# Run CUR processor tests
echo -e "${YELLOW}Running CUR Processor Tests...${NC}"
python tests/test_cur.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}CUR Processor Tests Passed${NC}"
else
    echo -e "${RED}CUR Processor Tests Failed${NC}"
fi
echo "========================================================"

# Run CUR fetcher tests
echo -e "${YELLOW}Running CUR Fetcher Tests...${NC}"
python tests/test_cur_fetcher.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}CUR Fetcher Tests Passed${NC}"
else
    echo -e "${RED}CUR Fetcher Tests Failed${NC}"
fi
echo "========================================================"

# Run Observe tests (dry run)
echo -e "${YELLOW}Running Observe Tests (dry run)...${NC}"
python tests/test_observe.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Observe Tests Passed${NC}"
else
    echo -e "${RED}Observe Tests Failed${NC}"
fi
echo "========================================================"

# Run integration test (salesforce, dry run)
echo -e "${YELLOW}Running Integration Tests (Salesforce, dry run)...${NC}"
python tests/test_integration.py salesforce
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Integration Tests (Salesforce) Passed${NC}"
else
    echo -e "${RED}Integration Tests (Salesforce) Failed${NC}"
fi
echo "========================================================"

# Run integration test (CUR, dry run)
echo -e "${YELLOW}Running Integration Tests (CUR, dry run)...${NC}"
python tests/test_integration.py cur
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Integration Tests (CUR) Passed${NC}"
else
    echo -e "${RED}Integration Tests (CUR) Failed${NC}"
fi
echo "========================================================"

echo -e "${BLUE}Test Suite Completed${NC}"