# hello-world -  sapir 1st project - web list
import React, { useState } from 'react';

function ShoppingList() {
  // Initialize an empty list of items
  const [items, setItems] = useState([]);

  // Function to add an item to the list
  const addItem = (item) => {
    setItems([...items, item]);
    localStorage.setItem('shoppingList', JSON.stringify([...items, item]));
  }

  // Function to remove an item from the list
  const removeItem = (item) => {
    setItems(items.filter((i) => i !== item));
    localStorage.setItem('shoppingList', JSON.stringify(items.filter((i) => i !== item)));
  }

  // Render the list of items
  return (
    <div>
      <h1>Shopping List</h1>
      <ul>
        {items.map((item) => (
          <li key={item}>
            {item} <button onClick={() => removeItem(item)}>Remove</button>
          </li>
        ))}
      </ul>
      <input type="text" placeholder="Add item" onKeyDown={(e) => e.key === 'Enter' ? addItem(e.target.value) : null}/>
    </div>
  );
}

export default ShoppingList;
