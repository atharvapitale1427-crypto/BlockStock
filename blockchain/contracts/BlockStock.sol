
 // SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract BlockStockLedger {
    address public owner;

    struct Movement {
        string material;
        uint256 quantity;
        bool stockIn;   
        string referenceId;
        uint256 timestamp;
        address recordedBy;
    }

    Movement[] private movements;

    event MovementRecorded(
        uint256 indexed movementId,
        string material,
        uint256 quantity,
        bool stockIn,
        string referenceId,
        address recordedBy
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can record");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function recordMovement(
        string calldata material,
        uint256 quantity,
        bool stockIn,
        string calldata referenceId
    ) external onlyOwner {
        require(bytes(material).length > 0, "Material required");
        require(quantity > 0, "Quantity must be positive");

        movements.push(Movement({
            material: material,
            quantity: quantity,
            stockIn: stockIn,
            referenceId: referenceId,
            timestamp: block.timestamp,
            recordedBy: msg.sender
        }));

        emit MovementRecorded(
            movements.length - 1,
            material,
            quantity,
            stockIn,
            referenceId,
            msg.sender
        );
    }

    function getMovementCount() external view returns (uint256) {
        return movements.length;
    }

    function getMovement(uint256 index)
        external
        view
        returns (Movement memory)
    {
        require(index < movements.length, "Invalid movement ID");
        return movements[index];
    }
}
