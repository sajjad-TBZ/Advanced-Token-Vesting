from web3 import Web3
from solcx import compile_standard, install_solc

print("Initializing...")
install_solc('0.8.0')

# 1. Token Contract (For testing the Vesting)
token_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
contract SimpleToken {
    string public name = "VestingToken";
    string public symbol = "VST";
    uint8 public decimals = 18;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    
    constructor(uint256 _supply) {
        balanceOf[msg.sender] = _supply * 10**uint256(decimals);
    }
    function transfer(address _to, uint256 _value) public returns (bool) {
        require(balanceOf[msg.sender] >= _value, "Not enough balance");
        balanceOf[msg.sender] -= _value;
        balanceOf[_to] += _value;
        return true;
    }
    function approve(address _spender, uint256 _value) public returns (bool) {
        allowance[msg.sender][_spender] = _value;
        return true;
    }
    function transferFrom(address _from, address _to, uint256 _value) public returns (bool) {
        require(balanceOf[_from] >= _value && allowance[_from][msg.sender] >= _value, "Not allowed");
        balanceOf[_from] -= _value;
        balanceOf[_to] += _value;
        allowance[_from][msg.sender] -= _value;
        return true;
    }
}
"""

# 2. Advanced Token Vesting Contract
vesting_source = """
pragma solidity ^0.8.0;

interface IERC20 {
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
}

contract TokenVesting {
    IERC20 public token;
    address public owner;
    bool private locked;

    struct Grant {
        uint256 totalAmount;
        uint256 releasedAmount;
        uint256 startTime;
        uint256 cliffDuration;
        uint256 vestingDuration;
        bool revoked;
    }

    mapping(address => Grant) public grants;

    event GrantCreated(address indexed beneficiary, uint256 amount, uint256 startTime, uint256 cliff, uint256 duration);
    event TokensReleased(address indexed beneficiary, uint256 amount);
    event GrantRevoked(address indexed beneficiary, uint256 amountRefunded);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }

    modifier nonReentrant() {
        require(!locked, "No reentrancy");
        locked = true;
        _;
        locked = false;
    }

    constructor(address _token) {
        token = IERC20(_token);
        owner = msg.sender;
    }

    function createGrant(
        address _beneficiary,
        uint256 _amount,
        uint256 _cliffDuration,
        uint256 _vestingDuration
    ) external onlyOwner {
        require(grants[_beneficiary].totalAmount == 0, "Grant already exists");
        require(_amount > 0, "Amount must be > 0");
        require(_vestingDuration > _cliffDuration, "Vesting must be > Cliff");

        require(token.transferFrom(msg.sender, address(this), _amount), "Token transfer failed");

        grants[_beneficiary] = Grant({
            totalAmount: _amount,
            releasedAmount: 0,
            startTime: block.timestamp,
            cliffDuration: _cliffDuration,
            vestingDuration: _vestingDuration,
            revoked: false
        });

        emit GrantCreated(_beneficiary, _amount, block.timestamp, _cliffDuration, _vestingDuration);
    }

    function vestedAmount(address _beneficiary) public view returns (uint256) {
        Grant memory grant = grants[_beneficiary];
        if (grant.totalAmount == 0) return 0;
        
        uint256 currentTime = block.timestamp;
        uint256 cliffTime = grant.startTime + grant.cliffDuration;

        if (currentTime < cliffTime) {
            return 0;
        } else if (currentTime >= grant.startTime + grant.vestingDuration) {
            return grant.totalAmount;
        } else {
            uint256 timeVested = currentTime - grant.startTime;
            return (grant.totalAmount * timeVested) / grant.vestingDuration;
        }
    }

    function release() external nonReentrant {
        Grant storage grant = grants[msg.sender];
        require(grant.totalAmount > 0, "No grant found");
        require(!grant.revoked, "Grant is revoked");

        uint256 vested = vestedAmount(msg.sender);
        uint256 unreleased = vested - grant.releasedAmount;
        require(unreleased > 0, "No tokens to release");

        grant.releasedAmount += unreleased;
        require(token.transfer(msg.sender, unreleased), "Transfer failed");

        emit TokensReleased(msg.sender, unreleased);
    }

    function revoke(address _beneficiary) external onlyOwner {
        Grant storage grant = grants[_beneficiary];
        require(grant.totalAmount > 0, "No grant found");
        require(!grant.revoked, "Already revoked");

        uint256 vested = vestedAmount(_beneficiary);
        uint256 refund = grant.totalAmount - vested;
        
        grant.revoked = true;
        grant.totalAmount = vested;

        if (refund > 0) {
            require(token.transfer(owner, refund), "Refund failed");
        }
        emit GrantRevoked(_beneficiary, refund);
    }
}
"""

print("Compiling contracts...")
compiled = compile_standard({
    "language": "Solidity",
    "sources": {"All.sol": {"content": token_source + vesting_source}},
    "settings": {"outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}}}
}, solc_version="0.8.0")

token_abi = compiled['contracts']['All.sol']['SimpleToken']['abi']
token_bytecode = compiled['contracts']['All.sol']['SimpleToken']['evm']['bytecode']['object']
vesting_abi = compiled['contracts']['All.sol']['TokenVesting']['abi']
vesting_bytecode = compiled['contracts']['All.sol']['TokenVesting']['evm']['bytecode']['object']

print("Connecting to Ganache...")
w3 = Web3(Web3.HTTPProvider("http://localhost:7545"))
if not w3.is_connected():
    print("Error: Ganache is not running!")
    exit()

# 👇 Enter your Private Key here 👇
private_key = "0x46d1f286b5b021b3b7e4fc2ad8b62cbb39ae8951dddd44c181fd1ce1bae1bb61"
account_1 = w3.eth.account.from_key(private_key)
account_2 = w3.eth.accounts[1] # The Beneficiary

def send_tx(contract_function):
    tx = contract_function.build_transaction({
        'from': account_1.address,
        'nonce': w3.eth.get_transaction_count(account_1.address),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    return w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))

print("\nDeploying Token...")
Token = w3.eth.contract(abi=token_abi, bytecode=token_bytecode)
receipt = send_tx(Token.constructor(1000000))
token_address = receipt.contractAddress
token = w3.eth.contract(address=token_address, abi=token_abi)

print("Deploying Vesting Contract...")
Vesting = w3.eth.contract(abi=vesting_abi, bytecode=vesting_bytecode)
receipt = send_tx(Vesting.constructor(token_address))
vesting_address = receipt.contractAddress
vesting = w3.eth.contract(address=vesting_address, abi=vesting_abi)
print(f"Vesting Contract deployed at: {vesting_address}")

print("\n--- Starting Test Scenarios ---")
print("1. Approving tokens for vesting...")
send_tx(token.functions.approve(vesting_address, 1000 * 10**18))

print("2. Creating Grant for Account 2 (Cliff: 10s, Total: 50s)...")
# Beneficiary: account_2, Amount: 1000, Cliff: 10 sec, Vesting: 50 sec
send_tx(vesting.functions.createGrant(account_2, 1000 * 10**18, 10, 50))

print("\n⏳ Simulating time jump (5 seconds) - Before Cliff...")
w3.provider.make_request("evm_increaseTime", [5])
w3.provider.make_request("evm_mine", [])
vested_before_cliff = vesting.functions.vestedAmount(account_2).call()
print(f"Vested amount before cliff: {vested_before_cliff / 10**18} Tokens (Expected: 0)")

print("\n⏳ Simulating time jump (10 seconds) - After Cliff...")
w3.provider.make_request("evm_increaseTime", [10])
w3.provider.make_request("evm_mine", [])
vested_after_cliff = vesting.functions.vestedAmount(account_2).call()
print(f"Vested amount after cliff (15s total): {vested_after_cliff / 10**18} Tokens")

print("\n3. Account 2 releasing vested tokens...")
# Using transact() for account_2 because Ganache has it unlocked by default
tx_hash = vesting.functions.release().transact({'from': account_2, 'gas': 200000})
w3.eth.wait_for_transaction_receipt(tx_hash)

balance_after_release = token.functions.balanceOf(account_2).call()
print(f"Beneficiary balance after release: {balance_after_release / 10**18} Tokens")

print("\n⏳ Simulating time jump (50 seconds) - Full Vesting complete...")
w3.provider.make_request("evm_increaseTime", [50])
w3.provider.make_request("evm_mine", [])
vested_full = vesting.functions.vestedAmount(account_2).call()
print(f"Vested amount after 50s total: {vested_full / 10**18} Tokens (Expected: 1000)")

print("\n4. Account 2 releasing remaining tokens...")
tx_hash = vesting.functions.release().transact({'from': account_2, 'gas': 200000})
w3.eth.wait_for_transaction_receipt(tx_hash)

final_balance = token.functions.balanceOf(account_2).call()
print(f"Final Beneficiary balance: {final_balance / 10**18} Tokens")